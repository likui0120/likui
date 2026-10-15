"""能耗：单表用量、全厂/车间合计、吨能耗、能耗费用。

单表用量 =（本期 − 上期）× 倍率；上期自动取之前最近一天的本期读数（跨月自动衔接）。
换表当天：用量 =（旧表最终读数 − 上期）+（本期 − 新表起始读数），再乘倍率。
计入方式：+ 计入合计，- 从合计扣减，ref 参考（只记录不进合计）。
吨能耗 = 合计用量 ÷ 当日总产量（吨），吨 = 斤 ÷ 2000。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ENERGIES, EnergyPrice, Meter, MeterReading, MeterVersion
from .versions import effective_rows

JIN_PER_TON = Decimal(2000)


def js(v):
    return None if v is None else str(v)


def prev_reading(db: Session, meter_id: int, day: date):
    return db.scalars(
        select(MeterReading)
        .where(MeterReading.meter_id == meter_id, MeterReading.date < day)
        .order_by(MeterReading.date.desc())
        .limit(1)
    ).first()


def prev_readings(db: Session, day: date) -> dict:
    """每块表在 day 之前最近一次的读数，一次查出。"""
    sub = (select(MeterReading.meter_id, func.max(MeterReading.date).label("d"))
           .where(MeterReading.date < day).group_by(MeterReading.meter_id).subquery())
    stmt = select(MeterReading).join(sub, (MeterReading.meter_id == sub.c.meter_id) & (MeterReading.date == sub.c.d))
    return {r.meter_id: r for r in db.scalars(stmt)}


def meter_usage(meter: Meter, ver: MeterVersion, rec: MeterReading | None, prev: MeterReading | None):
    """返回 (单表明细 dict, 提示 or None)。"""
    row = {"meter_id": meter.id, "name": meter.name, "energy": meter.energy, "mode": ver.mode,
           "factor": js(ver.factor), "factor_text": ver.factor_text, "plant": ver.plant,
           "workshop": ver.workshop, "reading": None, "prev": None, "prev_date": None, "usage": None}
    if rec is None:
        return row, "未抄表"
    row["reading"] = js(rec.reading)
    if ver.mode == "direct":
        row["usage"] = js(rec.reading * ver.factor)
        return row, None
    if rec.new_start is not None:
        # 换表
        diff = rec.reading - rec.new_start
        if prev is not None and rec.old_final is not None:
            diff += rec.old_final - prev.reading
        row.update(prev=js(prev.reading) if prev else None, prev_date=prev.date.isoformat() if prev else None,
                   replaced=True, old_final=js(rec.old_final), new_start=js(rec.new_start))
        row["usage"] = js(diff * ver.factor)
        return row, None
    if prev is None:
        row["note"] = "首次抄表，没有上期读数，当天不计用量"
        return row, None
    row["prev"], row["prev_date"] = js(prev.reading), prev.date.isoformat()
    if rec.reading < prev.reading:
        return row, f"本期读数 {rec.reading} 小于上期 {prev.reading}，请核对（换表请填新表起始读数）"
    row["usage"] = js((rec.reading - prev.reading) * ver.factor)
    return row, None


def calc_energy_day(db: Session, day: date, total_output_jin: Decimal):
    versions = effective_rows(db, MeterVersion, "meter_id", day)
    prices = {k: v.price for k, v in effective_rows(db, EnergyPrice, "energy", day).items()}
    meters = list(db.scalars(select(Meter).order_by(Meter.energy, Meter.sort, Meter.id)))
    rows, warnings = [], []
    totals = {e: {"plant": Decimal(0), "workshop": Decimal(0), "complete": True} for e in ENERGIES}
    today = {r.meter_id: r for r in db.scalars(select(MeterReading).where(MeterReading.date == day))}
    prevs = prev_readings(db, day)
    any_reading = bool(today)
    for m in meters:
        ver = versions.get(m.id)
        if ver is None or not ver.active:
            continue
        row, warn = meter_usage(m, ver, today.get(m.id), prevs.get(m.id))
        rows.append(row)
        counted = ver.plant in ("+", "-") or ver.workshop in ("+", "-")
        if warn and any_reading and (counted or row["reading"] is not None):
            warnings.append({"key": f"meter:{m.id}", "name": f"{ENERGIES[m.energy][0]}·{m.name}", "message": warn})
        u = Decimal(row["usage"]) if row["usage"] is not None else None
        t = totals[m.energy]
        for scope in ("plant", "workshop"):
            sign = getattr(ver, scope)
            if sign not in ("+", "-"):
                continue
            if u is None:
                t["complete"] = False
                continue
            t[scope] += u if sign == "+" else -u

    tons = total_output_jin / JIN_PER_TON if total_output_jin else None
    summary = {}
    cost_total = Decimal(0)
    for e, t in totals.items():
        price = prices.get(e)
        cost = t["plant"] * price if price is not None else None
        if cost is not None:
            cost_total += cost
        summary[e] = {
            "plant": js(t["plant"]), "workshop": js(t["workshop"]), "complete": t["complete"],
            "price": js(price), "cost": js(cost),
            "per_ton": js(t["plant"] / tons) if tons else None,
            "workshop_per_ton": js(t["workshop"] / tons) if tons and e == "water" else None,
            "outside_per_ton": js((t["plant"] - t["workshop"]) / tons) if tons and e == "water" else None,
        }
    data = {"meters": rows, "summary": summary, "cost_total": js(cost_total),
            "output_jin": js(total_output_jin), "output_ton": js(tons), "has_readings": any_reading}
    return data, warnings
