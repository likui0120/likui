"""基础资料接口。"""
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    ENERGIES, INCLUDE_MODES, MATERIAL_CATEGORIES, PRODUCT_TYPES, STAGES, TEAMS, AlertThreshold, AttrVersion, Bom, BomLine,
    ChangeLog,
    EnergyPrice, Material, MaterialPrice, MaterialStdYield, Meter, MeterVersion, PackSpec, PackSpecVersion,
    Product, ProductStdYield, SeasoningPrice,
)
from ..settings import all_settings, set_setting
from ..calc.versions import VERSIONED_ATTRS
from .common import apply_payload, flush_or_400, log_change, parse_bool, crud_router, parse_date, parse_dec, recalc_after, to_dict

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- 领域校验（写库前，不合法返回 400）

def _bad(msg):
    raise HTTPException(400, msg)


def _pos(v, label, allow_none=False, allow_zero=False):
    if v is None:
        if not allow_none:
            _bad(f"{label}不能为空")
        return
    if v < 0 or (v == 0 and not allow_zero):
        _bad(f"{label}必须大于 0" if not allow_zero else f"{label}不能是负数")


def _one_of(v, options, label):
    if v not in options:
        _bad(f"{label}只能是：{'、'.join(str(o) for o in options if o != '') or '空'}（收到 {v!r}）")


def v_material(db, r: Material):
    if not r.name:
        _bad("原料名称不能为空")
    _one_of(r.category, MATERIAL_CATEGORIES, "原料类别")


def v_material_std(db, r: MaterialStdYield):
    _pos(r.std_yield, "标准出率")  # 泡发类可以超过 100%，所以只限制大于 0
    if r.effective_date is None:
        _bad("生效日期不能为空")


def v_season(db, r: SeasoningPrice):
    _pos(r.price, "干调单价", allow_zero=True)
    m = db.get(Material, r.material_id)
    if m is None or m.category != "干调":
        _bad("干调价格只能设给类别为“干调”的原料")


def v_product(db, r: Product):
    if not r.name:
        _bad("产品名称不能为空")
    _one_of(r.ptype, PRODUCT_TYPES, "产品类型")
    _one_of(r.team, TEAMS, "生产班组")
    _pos(r.fallback_price, "标准单价", allow_none=True, allow_zero=True)
    _pos(r.unit_weight, "每袋/盒斤数", allow_none=True)
    if r.source_material_id is not None and db.get(Material, r.source_material_id) is None:
        _bad("指定的芝麻原料不存在")


def v_product_std(db, r: ProductStdYield):
    for attr, label in (("cook_yield", "熟制/拌馅标准出率"), ("cool_yield", "制冷标准出率"), ("pack_yield", "包装标准出率")):
        _pos(getattr(r, attr), label, allow_none=True)
    if r.effective_date is None:
        _bad("生效日期不能为空")


def v_spec_version(db, r: PackSpecVersion):
    _pos(r.bag_weight, "每袋斤数")
    _pos(r.fee, "袋费", allow_zero=True)


def v_meter(db, r: Meter):
    _one_of(r.energy, list(ENERGIES), "能源")
    if not r.name:
        _bad("计量表名称不能为空")


def v_meter_version(db, r: MeterVersion):
    _one_of(r.mode, ["reading", "direct"], "抄表方式")
    _pos(r.factor, "倍率")
    _one_of(r.plant or "", INCLUDE_MODES, "全厂计入方式")
    _one_of(r.workshop or "", INCLUDE_MODES, "车间计入方式")


def v_energy_price(db, r: EnergyPrice):
    _one_of(r.energy, list(ENERGIES), "能源")
    _pos(r.price, "能源单价", allow_zero=True)


def v_threshold(db, r: AlertThreshold):
    _one_of(r.scope, ["global", "category", "material", "stage", "product_stage"], "阈值范围")
    _pos(r.value, "阈值", allow_zero=True)
    if r.scope == "category":
        _one_of(r.category, MATERIAL_CATEGORIES, "原料类别")
    if r.scope == "material" and not r.material_id:
        _bad("请选择原料")
    if r.scope in ("stage", "product_stage"):
        _one_of(r.stage, list(STAGES), "环节")
    if r.scope == "product_stage" and not r.product_id:
        _bad("请选择产品")


def versioned_attrs_hook(entity: str):
    """原料/产品修改：影响计算的属性按“从哪天起生效”存版本，历史日期仍按当时的值算。

    请求体可带：
    - attr_effective_date：这些属性从哪天起生效（默认今天）
    - attr_correction：true 表示“之前录错了”，所有历史一起改
    其他字段（名称、编码、备注等）直接改。
    """
    fields = VERSIONED_ATTRS[entity]

    def hook(db: Session, row, payload: dict):
        eff = payload.pop("attr_effective_date", None)
        correction = parse_bool(payload.pop("attr_correction", False), "是否修正历史")
        old = {f: getattr(row, f) for f in fields}
        apply_payload(row, payload)
        new = {f: getattr(row, f) for f in fields}
        changed = {f: new[f] for f in fields if new[f] != old[f]}
        if not changed:
            return None
        versions = list(db.scalars(select(AttrVersion).where(
            AttrVersion.entity == entity, AttrVersion.entity_id == row.id).order_by(AttrVersion.effective_date)))
        if correction:
            for v in versions:
                v.data = {**v.data, **changed}
            log_change(db, row.__tablename__, row.id, "update", old, new, None, "修正历史：所有日期一起改")
            return None
        d = parse_date(eff) if eff else date.today()
        if not versions:
            # 第一次版本化：改之前的值作为“从最早起”的版本
            first = AttrVersion(entity=entity, entity_id=row.id, effective_date=date(1900, 1, 1), data=old)
            db.add(first)
            versions = [first]
        at = next((v for v in versions if v.effective_date == d), None)
        if at is not None:
            at.data = {**at.data, **changed}
        else:
            base = [v for v in versions if v.effective_date <= d]
            data = {**(base[-1].data if base else old), **changed}
            at = AttrVersion(entity=entity, entity_id=row.id, effective_date=d, data=data)
            db.add(at)
            versions = sorted(versions + [at], key=lambda v: v.effective_date)
        # 资料表本身保存最新一版的值
        for f, v in versions[-1].data.items():
            setattr(row, f, v)
        log_change(db, row.__tablename__, row.id, "update", old, changed, d, f"从 {d.isoformat()} 起生效")
        return d

    return hook


@router.get("/attr-versions")
def list_attr_versions(entity: str, entity_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(select(AttrVersion).where(AttrVersion.entity == entity, AttrVersion.entity_id == entity_id)
                      .order_by(AttrVersion.effective_date))
    return [to_dict(r) for r in rows]


@router.get("/change-log")
def list_change_log(limit: int = 200, db: Session = Depends(get_db)):
    rows = db.scalars(select(ChangeLog).order_by(ChangeLog.id.desc()).limit(min(limit, 1000)))
    return [to_dict(r) for r in rows]


HOOKS = {Material: versioned_attrs_hook("material"), Product: versioned_attrs_hook("product")}

for model, prefix, order, versioned, validate in [
    (Material, "/materials", (Material.category, Material.name), False, v_material),
    (MaterialStdYield, "/material-std-yields", (MaterialStdYield.material_id, MaterialStdYield.effective_date), True, v_material_std),
    (SeasoningPrice, "/seasoning-prices", (SeasoningPrice.material_id, SeasoningPrice.effective_date), True, v_season),
    (Product, "/products", (Product.sort, Product.team, Product.name), False, v_product),
    (ProductStdYield, "/product-std-yields", (ProductStdYield.product_id, ProductStdYield.effective_date), True, v_product_std),
    (PackSpec, "/pack-specs", (PackSpec.sort, PackSpec.id), False, None),
    (PackSpecVersion, "/pack-spec-versions", (PackSpecVersion.spec_id, PackSpecVersion.effective_date), True, v_spec_version),
    (Meter, "/meters", (Meter.energy, Meter.sort, Meter.id), False, v_meter),
    (MeterVersion, "/meter-versions", (MeterVersion.meter_id, MeterVersion.effective_date), True, v_meter_version),
    (EnergyPrice, "/energy-prices", (EnergyPrice.energy, EnergyPrice.effective_date), True, v_energy_price),
    (AlertThreshold, "/thresholds", (AlertThreshold.scope, AlertThreshold.id), False, v_threshold),
]:
    router.include_router(crud_router(model, prefix, order_by=order, versioned=versioned, validate=validate,
                                      update_hook=HOOKS.get(model)))



@router.get("/meta")
def meta():
    return {
        "material_categories": MATERIAL_CATEGORIES,
        "product_types": PRODUCT_TYPES,
        "teams": TEAMS,
        "energies": [{"key": k, "name": v[0], "unit": v[1]} for k, v in ENERGIES.items()],
        "include_modes": INCLUDE_MODES,
        "stages": [{"key": k, "name": v} for k, v in STAGES.items()],
    }


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    return all_settings(db)


@router.put("/settings")
def put_settings(payload: dict = Body(...), db: Session = Depends(get_db)):
    for k, v in payload.items():
        try:
            set_setting(db, k, str(v))
        except KeyError:
            raise HTTPException(400, f"未知设置项 {k}")
        except ValueError as e:
            raise HTTPException(400, str(e))
    recalc_after(db, None)
    return all_settings(db)


@router.post("/meters/with-version")
def create_meter(payload: dict = Body(...), db: Session = Depends(get_db)):
    """新增计量表并同时建立第一版配置。"""
    m = Meter(energy=payload.get("energy"), name=(payload.get("name") or "").strip(), sort=int(payload.get("sort") or 0))
    v_meter(db, m)
    db.add(m)
    db.flush()
    mv = MeterVersion(
        meter_id=m.id, effective_date=parse_date(payload.get("effective_date") or date.today()),
        mode=payload.get("mode") or "reading", factor=parse_dec(payload.get("factor") or 1),
        factor_text=payload.get("factor_text"), plant=payload.get("plant", "+"),
        workshop=payload.get("workshop", ""), active=True, note=payload.get("note"),
    )
    v_meter_version(db, mv)
    db.add(mv)
    flush_or_400(db)
    recalc_after(db, None)
    return to_dict(m)


@router.post("/pack-specs/with-version")
def create_spec(payload: dict = Body(...), db: Session = Depends(get_db)):
    if not (payload.get("name") or "").strip():
        _bad("规格名称不能为空")
    s = PackSpec(name=payload["name"].strip(), sort=int(payload.get("sort") or 0))
    db.add(s)
    db.flush()
    sv = PackSpecVersion(spec_id=s.id, effective_date=parse_date(payload.get("effective_date") or date.today()),
                         bag_weight=parse_dec(payload.get("bag_weight"), "每袋斤数"),
                         fee=parse_dec(payload.get("fee") or 0, "袋费"))
    v_spec_version(db, sv)
    db.add(sv)
    flush_or_400(db)
    recalc_after(db, None)
    return to_dict(s)


# ---------------------------------------------------------------- BOM

def bom_dict(db: Session, b: Bom) -> dict:
    mats = {m.id: m for m in db.scalars(select(Material))}
    prods = {p.id: p for p in db.scalars(select(Product))}
    lines = []
    for l in b.lines:
        if l.input_product_id:
            p = prods.get(l.input_product_id)
            name, kind = (p.name, p.ptype) if p else ("?", "?")
        else:
            m = mats.get(l.material_id)
            name = m.name if m else "?"
            kind = (m.category if m.category in ("干调", "水") else ("原料" if m.needs_process else "原料(不处理)")) if m else "?"
        lines.append({**to_dict(l), "name": name, "kind": kind})
    total = sum((l.qty for l in b.lines), start=0)
    return {**to_dict(b), "lines": lines, "total": str(total)}


@router.get("/boms")
def list_boms(product_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(Bom).order_by(Bom.product_id, Bom.effective_date.desc())
    if product_id:
        stmt = stmt.where(Bom.product_id == product_id)
    return [bom_dict(db, b) for b in db.scalars(stmt)]


@router.get("/boms/{bom_id}")
def get_bom(bom_id: int, db: Session = Depends(get_db)):
    b = db.get(Bom, bom_id)
    if b is None:
        raise HTTPException(404, "BOM 不存在")
    return bom_dict(db, b)


def write_lines(db: Session, b: Bom, lines: list[dict]):
    """先整批校验，全部通过才替换 BOM 行。"""
    if db.get(Product, b.product_id) is None:
        raise HTTPException(400, "BOM 的产品不存在")
    checked = []
    for i, l in enumerate(lines, start=1):
        qty = parse_dec(l.get("qty"), "数量")
        if qty is None:
            raise HTTPException(400, f"第 {i} 行缺数量")
        if qty <= 0:
            raise HTTPException(400, f"第 {i} 行数量必须大于 0")
        mid, pid = l.get("material_id") or None, l.get("input_product_id") or None
        if bool(mid) == bool(pid):
            raise HTTPException(400, f"第 {i} 行请选择一个投料（原料或半成品油/麻油）")
        if mid and db.get(Material, int(mid)) is None:
            raise HTTPException(400, f"第 {i} 行的原料不存在")
        if pid:
            up = db.get(Product, int(pid))
            if up is None or up.ptype not in ("半成品油", "麻油"):
                raise HTTPException(400, f"第 {i} 行：BOM 里只能引用半成品油或麻油，不能引用成品馅")
            if up.id == b.product_id:
                raise HTTPException(400, f"第 {i} 行：产品不能引用自己")
        checked.append((i, l, qty, mid, pid))
    if not checked:
        raise HTTPException(400, "BOM 至少要有一行投料")
    b.lines.clear()
    for i, l, qty, mid, pid in checked:
        b.lines.append(BomLine(line_no=int(l.get("line_no") or i), material_id=mid, input_product_id=pid,
                               qty=qty, note=l.get("note")))


@router.post("/boms")
def create_bom(payload: dict = Body(...), db: Session = Depends(get_db)):
    b = Bom(product_id=int(payload["product_id"]), effective_date=parse_date(payload["effective_date"]),
            note=payload.get("note"))
    write_lines(db, b, payload.get("lines") or [])
    db.add(b)
    flush_or_400(db)
    recalc_after(db, b.effective_date)
    return bom_dict(db, b)


@router.put("/boms/{bom_id}")
def update_bom(bom_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    b = db.get(Bom, bom_id)
    if b is None:
        raise HTTPException(404, "BOM 不存在")
    old = b.effective_date
    b.effective_date = parse_date(payload.get("effective_date") or b.effective_date)
    b.note = payload.get("note", b.note)
    if "lines" in payload:
        write_lines(db, b, payload["lines"])
    flush_or_400(db)
    recalc_after(db, min(old, b.effective_date))
    return bom_dict(db, b)


@router.delete("/boms/{bom_id}")
def delete_bom(bom_id: int, db: Session = Depends(get_db)):
    b = db.get(Bom, bom_id)
    if b is None:
        raise HTTPException(404, "BOM 不存在")
    d = b.effective_date
    db.delete(b)
    flush_or_400(db)
    recalc_after(db, d)
    return {"ok": True}


# ---------------------------------------------------------------- 原料 1 级单价

@router.get("/material-prices")
def list_prices(day: str, db: Session = Depends(get_db)):
    d = parse_date(day)
    rows = db.scalars(select(MaterialPrice).where(MaterialPrice.date == d)).all()
    return [to_dict(r) for r in rows]


@router.put("/material-prices/{day}")
def put_prices(day: str, payload: list[dict] = Body(...), db: Session = Depends(get_db)):
    """手工录入或修改当天 1 级单价：[{material_id, price}]，price 为空表示删除。"""
    d = parse_date(day)
    existing = {r.material_id: r for r in db.scalars(select(MaterialPrice).where(MaterialPrice.date == d))}
    for item in payload:
        mid = int(item["material_id"])
        price = parse_dec(item.get("price"), "单价")
        row = existing.get(mid)
        if price is None:
            if row is not None:
                db.delete(row)
            continue
        if row is None:
            db.add(MaterialPrice(material_id=mid, date=d, price=price, source="手工"))
        else:
            row.price, row.source = price, "手工"
    flush_or_400(db)
    return recalc_after(db, d)


@router.delete("/material-prices/{day}")
def clear_prices(day: str, db: Session = Depends(get_db)):
    d = parse_date(day)
    db.execute(delete(MaterialPrice).where(MaterialPrice.date == d))
    return recalc_after(db, d)


@router.post("/recalc")
def recalc(start: str | None = None, db: Session = Depends(get_db)):
    return recalc_after(db, parse_date(start) if start else None)
