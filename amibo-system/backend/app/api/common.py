"""接口通用工具：行转字典、请求体按列类型转换、通用增删改查。"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import Boolean, Date, Integer, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..calc.engine import recalc_from
from ..db import Dec, get_db


def to_dict(row, extra: dict | None = None) -> dict:
    out = {}
    for col in inspect(row.__class__).columns:
        v = getattr(row, col.key)
        if isinstance(v, Decimal):
            v = str(v)
        elif isinstance(v, (date, datetime)):
            v = v.isoformat()
        out[col.key] = v
    if extra:
        out.update(extra)
    return out


def jsonable(v):
    """递归把 Decimal / 日期转成字符串。"""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


def parse_date(v) -> date:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise HTTPException(400, f"日期格式不对：{v}")


def parse_dec(v, label="数值"):
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v).strip().replace(",", ""))
    except InvalidOperation:
        raise HTTPException(400, f"{label}不是有效数字：{v}")
    if not d.is_finite():
        raise HTTPException(400, f"{label}不是有效数字：{v}")
    return d


def parse_bool(v, label="开关"):
    if isinstance(v, bool) or v is None:
        return bool(v)
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y", "是", "√"):
        return True
    if s in ("false", "0", "no", "n", "否", ""):
        return False
    raise HTTPException(400, f"{label} 应是“是/否”：{v}")


def apply_payload(row, payload: dict, skip=("id",)):
    """按列类型把请求体写入行。"""
    cols = {c.key: c for c in inspect(row.__class__).columns}
    for k, v in payload.items():
        if k in skip or k not in cols:
            continue
        t = cols[k].type
        if isinstance(t, Dec):
            v = parse_dec(v, k)
        elif isinstance(t, Date):
            v = parse_date(v) if v not in (None, "") else None
        elif isinstance(t, Boolean):
            v = parse_bool(v, k)
        elif isinstance(t, Integer):
            try:
                v = int(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k} 应是整数：{v}")
        elif isinstance(v, str):
            v = v.strip() or None if cols[k].nullable else v.strip()
        setattr(row, k, v)
    return row


def integrity_400(db: Session, e: IntegrityError):
    db.rollback()
    msg = str(e.orig)
    if "UNIQUE" in msg:
        raise HTTPException(400, "已存在相同的记录（名称、编码或同一生效日期重复）")
    if "FOREIGN KEY" in msg:
        raise HTTPException(400, "这条资料已被其他数据引用，不能删除")
    raise HTTPException(400, msg)


def flush_or_400(db: Session):
    """把改动写进当前事务（还没提交），唯一/外键冲突转成 400。"""
    try:
        db.flush()
    except IntegrityError as e:
        integrity_400(db, e)


def recalc_after(db: Session, start: date | None):
    """资料或录入变动后重算受影响的日期，和改动一起提交。

    改动和重算在同一个事务里：重算失败就整体回滚，原始资料和计算结果不会对不上。
    """
    try:
        db.flush()
        summary = recalc_from(db, start)
        db.commit()
    except IntegrityError as e:
        integrity_400(db, e)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:  # 计算出错：本次修改不保存
        db.rollback()
        raise HTTPException(400, f"计算出错，本次修改没有保存：{type(e).__name__} {e}")
    return summary


def commit_only(db: Session):
    try:
        db.commit()
    except IntegrityError as e:
        integrity_400(db, e)


def crud_router(model, prefix: str, *, order_by=None, versioned: bool = False,
                recalc: bool = True, decorate=None, validate=None) -> APIRouter:
    """通用增删改查。versioned=True 的表按生效日期重算，否则改动后全部重算。"""
    r = APIRouter(prefix=prefix)

    @r.get("")
    def list_rows(db: Session = Depends(get_db)):
        stmt = select(model)
        if order_by is not None:
            stmt = stmt.order_by(*order_by)
        rows = db.scalars(stmt).all()
        return [decorate(db, x) if decorate else to_dict(x) for x in rows]

    def after(db, row_date):
        if recalc:
            recalc_after(db, row_date if versioned else None)
        else:
            commit_only(db)

    @r.post("")
    def create(payload: dict = Body(...), db: Session = Depends(get_db)):
        row = apply_payload(model(), payload)
        if validate:
            validate(db, row)
        db.add(row)
        flush_or_400(db)
        after(db, getattr(row, "effective_date", None))
        return to_dict(row)

    @r.put("/{row_id}")
    def update(row_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
        row = db.get(model, row_id)
        if row is None:
            raise HTTPException(404, "记录不存在")
        old = getattr(row, "effective_date", None)
        apply_payload(row, payload)
        if validate:
            validate(db, row)
        flush_or_400(db)
        new = getattr(row, "effective_date", None)
        after(db, min(d for d in (old, new) if d) if (old or new) else None)
        return to_dict(row)

    @r.delete("/{row_id}")
    def remove(row_id: int, db: Session = Depends(get_db)):
        row = db.get(model, row_id)
        if row is None:
            raise HTTPException(404, "记录不存在")
        d = getattr(row, "effective_date", None)
        db.delete(row)
        flush_or_400(db)
        after(db, d)
        return {"ok": True}

    return r
