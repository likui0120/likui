import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="amibo-test-")
os.environ["AMIBO_DATA_DIR"] = _tmp
os.environ["AMIBO_DB_URL"] = f"sqlite:///{_tmp}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def demo(db):
    from app.calc.engine import recalc_from
    from app.seed import init_base, init_demo

    init_base(db)
    init_demo(db)
    db.commit()
    recalc_from(db, None)
    return db
