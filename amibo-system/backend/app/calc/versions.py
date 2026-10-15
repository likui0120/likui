"""按生效日期取当天有效的版本。"""
from datetime import date
from types import SimpleNamespace

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


MATERIAL_ATTRS = ("needs_process", "category")
PRODUCT_ATTRS = ("ptype", "team", "cooled", "packed", "source_material_id", "fallback_price")
VERSIONED_ATTRS = {"material": MATERIAL_ATTRS, "product": PRODUCT_ATTRS}


def snapshot(row, data: dict | None = None) -> SimpleNamespace:
    """资料行的只读副本，用当天有效的属性版本覆盖。不改动数据库里的行。"""
    ns = SimpleNamespace(**{c.key: getattr(row, c.key) for c in row.__table__.columns})
    for k, v in (data or {}).items():
        setattr(ns, k, v)
    return ns


def attrs_on(db: Session, entity: str, day: date) -> dict[int, dict]:
    """{原料/产品 id: 当天有效的属性版本 data}，没有版本的不在结果里。"""
    from ..models import AttrVersion

    rows = effective_rows(db, AttrVersion, "entity_id", day, AttrVersion.entity == entity)
    return {k: v.data for k, v in rows.items()}


def materials_on(db: Session, day: date) -> dict:
    from ..models import Material

    ver = attrs_on(db, "material", day)
    return {m.id: snapshot(m, ver.get(m.id)) for m in db.scalars(select(Material))}


def products_on(db: Session, day: date) -> dict:
    from ..models import Product

    ver = attrs_on(db, "product", day)
    return {p.id: snapshot(p, ver.get(p.id)) for p in db.scalars(select(Product))}


def effective_one(db: Session, model, day: date, **filters):
    stmt = select(model).where(model.effective_date <= day)
    for k, v in filters.items():
        stmt = stmt.where(getattr(model, k) == v)
    return db.scalars(stmt.order_by(model.effective_date.desc()).limit(1)).first()
