"""数据库连接与通用类型。

所有重量、单价、出率都用 Decimal 计算，在 SQLite 里以文本保存，避免浮点误差。
"""
import os
from decimal import Decimal
from pathlib import Path

from sqlalchemy import String, TypeDecorator, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(os.environ.get("AMIBO_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_URL = os.environ.get("AMIBO_DB_URL", f"sqlite:///{DATA_DIR / 'amibo.db'}")


class Dec(TypeDecorator):
    """以文本保存的 Decimal，读写都不丢精度。"""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            return None
        return str(Decimal(str(value)))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value)


class Base(DeclarativeBase):
    pass


def make_engine(url: str = DB_URL):
    eng = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return eng


def migrate(eng, metadata):
    """给已有数据库补上新加的列（create_all 只建新表，不改旧表）。

    只做“加列”这一种迁移：新列都允许为空，旧数据不受影响；计算结果表的新列下次重算时填上。
    """
    from sqlalchemy import inspect, text

    insp = inspect(eng)
    added = []
    with eng.begin() as conn:
        for table in metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = col.type.compile(dialect=eng.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}'))
                added.append(f"{table.name}.{col.name}")
    return added


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
