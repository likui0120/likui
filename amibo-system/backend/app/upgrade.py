"""启动时升级旧数据库：先备份，再补新列，再把已有日期重算一遍填上新列。

重算要是失败（比如中途断电），数据库里留着“待回填”标记，下次启动会接着重算，不会因为列已经加过就跳过。
"""
import logging

from sqlalchemy import select

from .db import Base, SessionLocal, engine, migrate
from .models import Setting

log = logging.getLogger("amibo.upgrade")
PENDING_KEY = "_backfill_pending"


def upgrade() -> dict:
    out = {"backup": None, "added": [], "backfilled": False}
    missing = migrate(engine, Base.metadata, dry_run=True)
    if missing:
        try:
            from . import backup

            out["backup"] = backup.make_backup("before-upgrade").get("name")
        except Exception as e:  # 新装的空库等情况备份不了，不影响升级
            log.warning("升级前备份失败：%s", e)
        out["added"] = migrate(engine, Base.metadata)
    with SessionLocal() as db:
        flag = db.get(Setting, PENDING_KEY)
        if out["added"] and flag is None:
            flag = Setting(key=PENDING_KEY, value="1")
            db.add(flag)
            db.commit()
        if flag is None:
            return out
        from .calc.engine import recalc_from

        try:
            recalc_from(db, None)
            db.delete(db.scalars(select(Setting).where(Setting.key == PENDING_KEY)).one())
            db.commit()
            out["backfilled"] = True
        except Exception as e:
            db.rollback()
            log.error("升级后重算失败，下次启动会重试：%s", e)
            out["error"] = str(e)
    return out
