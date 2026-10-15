"""Codex 审查（CODEX_CLAUDE沟通.md）提出问题的回归测试。"""
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.calc import engine as eng
from app.db import SessionLocal
from app.main import app
from app.models import AlertThreshold, CalcProduct, DailyProduction, Material, Product

client = TestClient(app)
DAY = "2026-10-14"


def _row(name):
    d = client.get(f"/api/daily/{DAY}").json()
    return next(r for r in d["production"] if r["name"] == name)


def _saved_output(pid):
    with SessionLocal() as s:
        return s.scalars(select(DailyProduction.output_weight).where(
            DailyProduction.product_id == pid, DailyProduction.date == eng.date.fromisoformat(DAY))).first()


def test_a02_zero_output_rejected_and_nothing_saved(demo):
    fs = _row("粉丝馅料")
    before = _saved_output(fs["product_id"])
    r = client.put(f"/api/daily/{DAY}/production", json=[{**fs, "output_weight": "0"}])
    assert r.status_code == 400 and "不能为 0" in r.json()["detail"]
    assert _saved_output(fs["product_id"]) == before


def test_a02_engine_survives_zero_in_old_data(demo):
    """旧数据里已有 0 也不能让整次重算崩掉。"""
    db = demo
    p = db.scalars(select(Product).where(Product.name == "粉丝馅料")).one()
    rec = db.scalars(select(DailyProduction).where(DailyProduction.product_id == p.id)).first()
    rec.output_weight = Decimal(0)
    db.flush()
    eng.recalc_from(db, None)
    cp = db.scalars(select(CalcProduct).where(CalcProduct.product_id == p.id, CalcProduct.date == rec.date)).one()
    assert cp.ok is False
    db.rollback()


def test_a03_failed_recalc_rolls_back_the_save(demo, monkeypatch):
    fs = _row("粉丝馅料")
    before = _saved_output(fs["product_id"])

    def boom(*a, **k):
        raise RuntimeError("模拟计算失败")

    monkeypatch.setattr(eng, "recalc_day", boom)
    r = client.put(f"/api/daily/{DAY}/production", json=[{**fs, "output_weight": "1234"}])
    assert r.status_code == 400 and "没有保存" in r.json()["detail"]
    assert _saved_output(fs["product_id"]) == before


def test_a06_zero_threshold_is_respected(demo):
    db = demo
    ginger = db.scalars(select(Material).where(Material.name == "姜")).one()
    th = eng.Thresholds(db)
    assert th.for_material(ginger) == th.glob
    db.add(AlertThreshold(scope="material", material_id=ginger.id, value=Decimal(0)))
    db.flush()
    assert eng.Thresholds(db).for_material(ginger) == 0
    db.rollback()


def test_a06_daily_rows_carry_threshold(demo):
    d = client.get(f"/api/daily/{DAY}").json()
    assert all("threshold" in r for r in d["process"] + d["production"] + d["cooling"] + d["packing"])


def test_a07_bool_strings_and_bad_values(demo):
    mats = client.get("/api/materials").json()
    ginger = next(m for m in mats if m["name"] == "姜")
    r = client.put(f"/api/materials/{ginger['id']}", json={"needs_process": "false"})
    assert r.status_code == 200 and r.json()["needs_process"] is False
    assert client.put(f"/api/materials/{ginger['id']}", json={"needs_process": "maybe"}).status_code == 400
    assert client.put(f"/api/materials/{ginger['id']}", json={"category": "不存在的类别"}).status_code == 400
    assert client.put("/api/settings", json={"sesame_rule": "abc"}).status_code == 400
    assert client.put("/api/settings", json={"global_threshold": "-1"}).status_code == 400
