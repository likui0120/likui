"""按生效日期取当天有效的版本。"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session


def effective_rows(db: Session, model, key_col: str, day: date, extra=None):
    """返回 {key: 当天有效的那一行}：同一个 key 取 effective_date <= day 中最新的一条。"""
    stmt = select(model).where(model.effective_date <= day)
    if extra is not None:
        stmt = stmt.where(extra)
    stmt = stmt.order_by(getattr(model, key_col), model.effective_date)
    out = {}
    for row in db.scalars(stmt):
        out[getattr(row, key_col)] = row  # 按日期升序，后面的覆盖前面的
    return out


def effective_one(db: Session, model, day: date, **filters):
    stmt = select(model).where(model.effective_date <= day)
    for k, v in filters.items():
        stmt = stmt.where(getattr(model, k) == v)
    return db.scalars(stmt.order_by(model.effective_date.desc()).limit(1)).first()
