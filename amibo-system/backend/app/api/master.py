"""基础资料接口。"""
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    ENERGIES, INCLUDE_MODES, MATERIAL_CATEGORIES, PRODUCT_TYPES, STAGES, TEAMS, AlertThreshold, Bom, BomLine,
    EnergyPrice, Material, MaterialPrice, MaterialStdYield, Meter, MeterVersion, PackSpec, PackSpecVersion,
    Product, ProductStdYield, SeasoningPrice,
)
from ..settings import all_settings, set_setting
from .common import commit_or_400, crud_router, parse_date, parse_dec, recalc_after, to_dict

router = APIRouter(prefix="/api")

for model, prefix, order, versioned in [
    (Material, "/materials", (Material.category, Material.name), False),
    (MaterialStdYield, "/material-std-yields", (MaterialStdYield.material_id, MaterialStdYield.effective_date), True),
    (SeasoningPrice, "/seasoning-prices", (SeasoningPrice.material_id, SeasoningPrice.effective_date), True),
    (Product, "/products", (Product.sort, Product.team, Product.name), False),
    (ProductStdYield, "/product-std-yields", (ProductStdYield.product_id, ProductStdYield.effective_date), True),
    (PackSpec, "/pack-specs", (PackSpec.sort, PackSpec.id), False),
    (PackSpecVersion, "/pack-spec-versions", (PackSpecVersion.spec_id, PackSpecVersion.effective_date), True),
    (Meter, "/meters", (Meter.energy, Meter.sort, Meter.id), False),
    (MeterVersion, "/meter-versions", (MeterVersion.meter_id, MeterVersion.effective_date), True),
    (EnergyPrice, "/energy-prices", (EnergyPrice.energy, EnergyPrice.effective_date), True),
    (AlertThreshold, "/thresholds", (AlertThreshold.scope, AlertThreshold.id), False),
]:
    router.include_router(crud_router(model, prefix, order_by=order, versioned=versioned))


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
    db.commit()
    recalc_after(db, None)
    return all_settings(db)


@router.post("/meters/with-version")
def create_meter(payload: dict = Body(...), db: Session = Depends(get_db)):
    """新增计量表并同时建立第一版配置。"""
    m = Meter(energy=payload["energy"], name=payload["name"].strip(), sort=int(payload.get("sort") or 0))
    db.add(m)
    db.flush()
    db.add(MeterVersion(
        meter_id=m.id, effective_date=parse_date(payload.get("effective_date") or date.today()),
        mode=payload.get("mode") or "reading", factor=parse_dec(payload.get("factor") or 1),
        factor_text=payload.get("factor_text"), plant=payload.get("plant", "+"),
        workshop=payload.get("workshop", ""), active=True, note=payload.get("note"),
    ))
    commit_or_400(db)
    recalc_after(db, None)
    return to_dict(m)


@router.post("/pack-specs/with-version")
def create_spec(payload: dict = Body(...), db: Session = Depends(get_db)):
    s = PackSpec(name=payload["name"].strip(), sort=int(payload.get("sort") or 0))
    db.add(s)
    db.flush()
    db.add(PackSpecVersion(spec_id=s.id, effective_date=parse_date(payload.get("effective_date") or date.today()),
                           bag_weight=parse_dec(payload["bag_weight"]), fee=parse_dec(payload.get("fee") or 0)))
    commit_or_400(db)
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


def write_lines(b: Bom, lines: list[dict]):
    b.lines.clear()
    for i, l in enumerate(lines, start=1):
        qty = parse_dec(l.get("qty"), "数量")
        if qty is None:
            raise HTTPException(400, f"第 {i} 行缺数量")
        mid, pid = l.get("material_id") or None, l.get("input_product_id") or None
        if bool(mid) == bool(pid):
            raise HTTPException(400, f"第 {i} 行请选择一个投料（原料或半成品油/麻油）")
        b.lines.append(BomLine(line_no=int(l.get("line_no") or i), material_id=mid, input_product_id=pid,
                               qty=qty, note=l.get("note")))


@router.post("/boms")
def create_bom(payload: dict = Body(...), db: Session = Depends(get_db)):
    b = Bom(product_id=int(payload["product_id"]), effective_date=parse_date(payload["effective_date"]),
            note=payload.get("note"))
    write_lines(b, payload.get("lines") or [])
    db.add(b)
    commit_or_400(db)
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
        write_lines(b, payload["lines"])
    commit_or_400(db)
    recalc_after(db, min(old, b.effective_date))
    return bom_dict(db, b)


@router.delete("/boms/{bom_id}")
def delete_bom(bom_id: int, db: Session = Depends(get_db)):
    b = db.get(Bom, bom_id)
    if b is None:
        raise HTTPException(404, "BOM 不存在")
    d = b.effective_date
    db.delete(b)
    commit_or_400(db)
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
    commit_or_400(db)
    return recalc_after(db, d)


@router.delete("/material-prices/{day}")
def clear_prices(day: str, db: Session = Depends(get_db)):
    d = parse_date(day)
    db.execute(delete(MaterialPrice).where(MaterialPrice.date == d))
    db.commit()
    return recalc_after(db, d)


@router.post("/recalc")
def recalc(start: str | None = None, db: Session = Depends(get_db)):
    return recalc_after(db, parse_date(start) if start else None)
