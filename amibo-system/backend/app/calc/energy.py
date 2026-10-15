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
    if prev is not None:
        days = (rec.date - prev.date).days
        if days > 1:
            # 漏抄了几天：读数差是这几天的合计，不平均摊到每天，只标出区间
            row["interval_days"] = days
            row["note"] = f"区间用量：{prev.date:%m-%d} 至 {rec.date:%m-%d} 共 {days} 天"
            if (prev.date.year, prev.date.month) != (rec.date.year, rec.date.month):
                row["cross_month"] = True
                row["note"] += "（跨月，含上月用量）"
    if rec.new_start is not None:
        # 换表
        diff = rec.reading - rec.new_start
        if prev is not None and rec.old_final is not None:
            diff += rec.old_final - prev.reading
        elif prev is not None:
            row["partial"] = True
            row["note"] = "换表没填旧表最终读数，只算了新表部分"
        row.update(prev=js(prev.reading) if prev else None, prev_date=prev.date.isoformat() if prev else None,
                   replaced=True, old_final=js(rec.old_final), new_start=js(rec.new_start))
        row["usage"] = js(diff * ver.factor)
        return row, (row["note"] if row.get("partial") else None)
    if prev is None:
        row["first"] = True
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
    totals = {e: {"plant": Decimal(0), "workshop": Decimal(0), "complete": True, "interval": False,
                  "missing": [], "notes": []} for e in ENERGIES}
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
        if counted:
            if u is None:
                t["missing"].append(m.name + ("（首次抄表）" if row.get("first") else "（未抄表）" if row["reading"] is None
                                              else "（读数有误）"))
            if row.get("interval_days"):
                t["interval"] = True
                t["notes"].append(f"{m.name} {row['note']}")
            if row.get("partial"):
                t["complete"] = False
                t["notes"].append(f"{m.name} {row['note']}")
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
    cost_complete = True
    notes = []
    for e, t in totals.items():
        ename = ENERGIES[e][0]
        price = prices.get(e)
        cost = t["plant"] * price if price is not None else None
        if cost is not None:
            cost_total += cost
        else:
            cost_complete = False
            if any_reading:
                notes.append(f"{ename}：没有有效的能源单价，能耗费用不含{ename}")
        if t["missing"] and any_reading:
            notes.append(f"{ename}：{'、'.join(t['missing'])}，合计不完整")
        notes.extend(f"{ename}：{n}" for n in t["notes"])
        # 吨能耗只在当天合计完整、且不含跨日区间时算；否则分子不是“当天”的用量
        per_ton_ok = bool(tons) and t["complete"] and not t["interval"]
        if t["interval"] and any_reading:
            notes.append(f"{ename}：含跨日区间用量，当天吨耗不计（月报按入账日累计）")
        summary[e] = {
            "plant": js(t["plant"]), "workshop": js(t["workshop"]), "complete": t["complete"],
            "interval": t["interval"], "missing": t["missing"],
            "price": js(price), "cost": js(cost),
            "per_ton": js(t["plant"] / tons) if per_ton_ok else None,
            "workshop_per_ton": js(t["workshop"] / tons) if per_ton_ok and e == "water" else None,
            "outside_per_ton": js((t["plant"] - t["workshop"]) / tons) if per_ton_ok and e == "water" else None,
        }
    if any_reading and not tons:
        notes.append("当天没有总产量，吨能耗不计")
    complete = any_reading and cost_complete and all(t["complete"] and not t["interval"] for t in totals.values())
    data = {"meters": rows, "summary": summary, "cost_total": js(cost_total), "cost_complete": cost_complete,
            "output_jin": js(total_output_jin), "output_ton": js(tons), "has_readings": any_reading,
            "complete": complete, "notes": notes if any_reading else ["当天没有抄表"]}
    return data, warnings
