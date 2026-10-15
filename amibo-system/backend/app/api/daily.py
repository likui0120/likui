"""每日录入接口。每次保存后从当天往后重算，并返回当天的异常与提示。"""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..calc.energy import prev_reading
from ..calc.engine import Thresholds
from ..calc.versions import effective_rows
from ..db import get_db
from ..models import (
    Bom, CalcIssue, DailyCooling, DailyMaterialProcess, DailyPacking, DailyPackingBag, DailyProduction,
    Material, MaterialPrice, MaterialStdYield, Meter, MeterReading, MeterVersion, PackSpec, PackSpecVersion,
    Product, ProductStdYield,
)
from .common import flush_or_400, parse_date, parse_dec, recalc_after, to_dict

router = APIRouter(prefix="/api/daily")


def s(v):
    return None if v is None else str(v)


def day_issues(db: Session, d):
    return [to_dict(i) for i in db.scalars(select(CalcIssue).where(CalcIssue.date == d).order_by(CalcIssue.kind, CalcIssue.id))]


@router.get("/{day}")
def get_day(day: str, db: Session = Depends(get_db)):
    d = parse_date(day)
    mats = list(db.scalars(select(Material).order_by(Material.category, Material.name)))
    mat_std = effective_rows(db, MaterialStdYield, "material_id", d)
    th = Thresholds(db)  # 录入页即时标红和后端异常用同一套阈值
    proc = {r.material_id: r for r in db.scalars(select(DailyMaterialProcess).where(DailyMaterialProcess.date == d))}
    process = [{
        "material_id": m.id, "name": m.name, "code": m.code, "category": m.category,
        "threshold": s(th.for_material(m)),
        "std_yield": s(mat_std[m.id].std_yield) if m.id in mat_std else None,
        "qty1": s(proc[m.id].qty1) if m.id in proc else None,
        "qty2": s(proc[m.id].qty2) if m.id in proc else None,
    } for m in mats if (m.needs_process and m.active) or m.id in proc]

    prods = list(db.scalars(select(Product).order_by(Product.sort, Product.team, Product.name)))
    pstd = effective_rows(db, ProductStdYield, "product_id", d)
    boms = effective_rows(db, Bom, "product_id", d)
    prod = {r.product_id: r for r in db.scalars(select(DailyProduction).where(DailyProduction.date == d))}
    cool = {r.product_id: r for r in db.scalars(select(DailyCooling).where(DailyCooling.date == d))}
    pack = {r.product_id: r for r in db.scalars(select(DailyPacking).where(DailyPacking.date == d))}

    def std(pid, attr):
        r = pstd.get(pid)
        return s(getattr(r, attr)) if r else None

    production, sesame, cooling, packing = [], [], [], []
    for p in prods:
        if not p.active and p.id not in prod:
            continue
        rec = prod.get(p.id)
        base = {"product_id": p.id, "name": p.name, "code": p.code, "team": p.team, "ptype": p.ptype}
        if p.ptype == "麻油":
            sesame.append({**base, "qty_in": s(rec.qty_in) if rec else None,
                           "output_weight": s(rec.output_weight) if rec else None, "std_yield": std(p.id, "cook_yield"),
                           "threshold": s(th.for_product(p.id, "oil"))})
            continue
        bom = boms.get(p.id)
        production.append({**base, "per_batch": s(sum(l.qty for l in bom.lines)) if bom and bom.lines else None,
                           "has_bom": bom is not None, "std_yield": std(p.id, "cook_yield"),
                           "threshold": s(th.for_product(p.id, "cook")),
                           "batches": s(rec.batches) if rec else None,
                           "output_weight": s(rec.output_weight) if rec else None})
        if p.cooled:
            c = cool.get(p.id)
            cooling.append({**base, "output_weight": s(rec.output_weight) if rec else None,
                            "std_yield": std(p.id, "cool_yield"), "threshold": s(th.for_product(p.id, "cool")),
                            "cooled_weight": s(c.cooled_weight) if c else None})
        if p.packed and p.ptype == "成品馅":
            k = pack.get(p.id)
            c = cool.get(p.id)
            default_pre = (c.cooled_weight if c else None) if p.cooled else (rec.output_weight if rec else None)
            packing.append({**base, "cooled": p.cooled, "default_prepack": s(default_pre),
                            "std_yield": std(p.id, "pack_yield"), "threshold": s(th.for_product(p.id, "pack")),
                            "packed_weight": s(k.packed_weight) if k else None,
                            "prepack_weight": s(k.prepack_weight) if k else None,
                            "bags": {str(b.spec_id): s(b.bags) for b in k.bags} if k else {}})

    specs = effective_rows(db, PackSpecVersion, "spec_id", d)
    spec_list = [{"spec_id": sp.id, "name": sp.name, "bag_weight": s(specs[sp.id].bag_weight), "fee": s(specs[sp.id].fee)}
                 for sp in db.scalars(select(PackSpec).where(PackSpec.active.is_(True)).order_by(PackSpec.sort, PackSpec.id))
                 if sp.id in specs]

    mvers = effective_rows(db, MeterVersion, "meter_id", d)
    reads = {r.meter_id: r for r in db.scalars(select(MeterReading).where(MeterReading.date == d))}
    meters = []
    for m in db.scalars(select(Meter).order_by(Meter.energy, Meter.sort, Meter.id)):
        v = mvers.get(m.id)
        if v is None or not v.active:
            continue
        pr = prev_reading(db, m.id, d) if v.mode == "reading" else None
        r = reads.get(m.id)
        meters.append({"meter_id": m.id, "energy": m.energy, "name": m.name, "mode": v.mode,
                       "factor": s(v.factor), "factor_text": v.factor_text, "plant": v.plant, "workshop": v.workshop,
                       "prev": s(pr.reading) if pr else None, "prev_date": pr.date.isoformat() if pr else None,
                       "reading": s(r.reading) if r else None, "old_final": s(r.old_final) if r else None,
                       "new_start": s(r.new_start) if r else None})

    prices = {r.material_id: r for r in db.scalars(select(MaterialPrice).where(MaterialPrice.date == d))}
    price_list = [{"material_id": m.id, "name": m.name, "code": m.code, "category": m.category,
                   "price": s(prices[m.id].price) if m.id in prices else None,
                   "source": prices[m.id].source if m.id in prices else None}
                  for m in mats if m.category not in ("干调", "水") and (m.active or m.id in prices)]

    return {"date": d.isoformat(), "process": process, "production": production, "sesame": sesame,
            "cooling": cooling, "packing": packing, "specs": spec_list, "meters": meters,
            "prices": price_list, "issues": day_issues(db, d)}


def empty(*vals):
    return all(v in (None, "") for v in vals)


def upsert(db, model, d, key_field, key, values: dict | None):
    row = db.scalars(select(model).where(model.date == d, getattr(model, key_field) == key)).first()
    if values is None:
        if row is not None:
            db.delete(row)
        return None
    if row is None:
        row = model(date=d, **{key_field: key})
        db.add(row)
    for k, v in values.items():
        setattr(row, k, v)
    return row


def finish(db: Session, d):
    flush_or_400(db)
    summary = recalc_after(db, d)
    return {"ok": True, "recalc": summary, "issues": day_issues(db, d)}


def need(v, label, name, positive=False, hint=""):
    """必填数值。positive=True 时必须大于 0（做分母的重量，0 会让出率和单价算不出来）。"""
    x = parse_dec(v, label)
    if x is None:
        raise HTTPException(400, f"{name}：{label}不能为空")
    if x < 0:
        raise HTTPException(400, f"{name}：{label}不能是负数")
    if positive and x == 0:
        raise HTTPException(400, f"{name}：{label}不能为 0{hint}")
    return x


SCRAP_HINT = "。如果当天整批报废，请清空这一行，并在异常清单里备注原因"


@router.put("/{day}/process")
def save_process(day: str, rows: list[dict] = Body(...), db: Session = Depends(get_db)):
    d = parse_date(day)
    for r in rows:
        mid = int(r["material_id"])
        name = r.get("name") or mid
        if empty(r.get("qty1"), r.get("qty2")):
            upsert(db, DailyMaterialProcess, d, "material_id", mid, None)
            continue
        q1 = need(r.get("qty1"), "1 级领用量", name, positive=True)
        q2 = need(r.get("qty2"), "2 级称重", name, positive=True, hint="。当天没处理就把两格都清空")
        upsert(db, DailyMaterialProcess, d, "material_id", mid, {"qty1": q1, "qty2": q2})
    return finish(db, d)


@router.put("/{day}/production")
def save_production(day: str, rows: list[dict] = Body(...), db: Session = Depends(get_db)):
    d = parse_date(day)
    for r in rows:
        pid = int(r["product_id"])
        name = r.get("name") or pid
        if empty(r.get("batches"), r.get("output_weight")):
            upsert(db, DailyProduction, d, "product_id", pid, None)
            continue
        b = need(r.get("batches"), "锅数/机数", name, positive=True)
        w = need(r.get("output_weight"), "出锅重/出机重", name, positive=True, hint=SCRAP_HINT)
        upsert(db, DailyProduction, d, "product_id", pid, {"batches": b, "output_weight": w, "qty_in": None})
    return finish(db, d)


@router.put("/{day}/sesame")
def save_sesame(day: str, rows: list[dict] = Body(...), db: Session = Depends(get_db)):
    d = parse_date(day)
    for r in rows:
        pid = int(r["product_id"])
        name = r.get("name") or "麻油"
        if empty(r.get("qty_in"), r.get("output_weight")):
            upsert(db, DailyProduction, d, "product_id", pid, None)
            continue
        q = need(r.get("qty_in"), "芝麻用量", name, positive=True)
        w = need(r.get("output_weight"), "麻油产量", name, positive=True, hint=SCRAP_HINT)
        upsert(db, DailyProduction, d, "product_id", pid, {"qty_in": q, "output_weight": w, "batches": None})
    return finish(db, d)


@router.put("/{day}/cooling")
def save_cooling(day: str, rows: list[dict] = Body(...), db: Session = Depends(get_db)):
    d = parse_date(day)
    for r in rows:
        pid = int(r["product_id"])
        if empty(r.get("cooled_weight")):
            upsert(db, DailyCooling, d, "product_id", pid, None)
            continue
        upsert(db, DailyCooling, d, "product_id", pid,
               {"cooled_weight": need(r["cooled_weight"], "打冷出机重", r.get("name") or pid,
                                      positive=True, hint=SCRAP_HINT)})
    return finish(db, d)


@router.put("/{day}/packing")
def save_packing(day: str, rows: list[dict] = Body(...), db: Session = Depends(get_db)):
    d = parse_date(day)
    for r in rows:
        pid = int(r["product_id"])
        name = r.get("name") or pid
        bags = {int(k): parse_dec(v, "袋数") for k, v in (r.get("bags") or {}).items() if v not in (None, "")}
        if empty(r.get("packed_weight")) and not bags:
            upsert(db, DailyPacking, d, "product_id", pid, None)
            continue
        packed = need(r.get("packed_weight"), "包装入库量", name, positive=True, hint=SCRAP_HINT)
        pre = parse_dec(r.get("prepack_weight"), "包装前重量")
        if pre is not None and pre <= 0:
            raise HTTPException(400, f"{name}：包装前重量必须大于 0（留空则取上一环节产出）")
        for n in bags.values():
            if n < 0 or n != n.to_integral_value():
                raise HTTPException(400, f"{name}：袋数应是不小于 0 的整数")
        row = upsert(db, DailyPacking, d, "product_id", pid, {"packed_weight": packed, "prepack_weight": pre})
        row.bags.clear()
        for spec_id, n in bags.items():
            if n:
                row.bags.append(DailyPackingBag(spec_id=spec_id, bags=n))
    return finish(db, d)


@router.put("/{day}/meters")
def save_meters(day: str, rows: list[dict] = Body(...), db: Session = Depends(get_db)):
    d = parse_date(day)
    for r in rows:
        mid = int(r["meter_id"])
        if empty(r.get("reading")):
            upsert(db, MeterReading, d, "meter_id", mid, None)
            continue
        name = r.get("name") or mid
        reading = need(r["reading"], "本期读数", name)
        old_final = parse_dec(r.get("old_final"), "旧表最终读数")
        new_start = parse_dec(r.get("new_start"), "新表起始读数")
        if old_final is not None and new_start is None:
            raise HTTPException(400, f"{name}：换表要同时填新表起始读数")
        if new_start is not None:
            if new_start < 0 or (old_final is not None and old_final < 0):
                raise HTTPException(400, f"{name}：换表读数不能是负数")
            if reading < new_start:
                raise HTTPException(400, f"{name}：本期读数小于新表起始读数，请核对")
        upsert(db, MeterReading, d, "meter_id", mid, {
            "reading": reading, "old_final": old_final, "new_start": new_start,
        })
    return finish(db, d)
