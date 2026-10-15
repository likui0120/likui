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


def test_a02_zero_output_kept_as_total_loss(demo):
    """出锅重 0 = 整批报废：原始记录保留，提示全损和损失金额，不出单位成本。"""
    fs = _row("粉丝馅料")
    r = client.put(f"/api/daily/{DAY}/production", json=[{**fs, "output_weight": "0"}])
    assert r.status_code == 200, r.text
    assert _saved_output(fs["product_id"]) == 0
    loss = [i for i in r.json()["issues"] if i["object_name"] == "粉丝馅料" and "全损" in i["message"]]
    assert loss and loss[0]["kind"] == "alert" and "损失投料成本" in loss[0]["message"]
    c = client.get("/api/reports/cost", params={"start": DAY, "end": DAY}).json()["rows"]
    row = next(x for x in c if x["product_id"] == fs["product_id"])
    assert row["final_a"] is None


def test_a02_zero_input_still_rejected(demo):
    fs = _row("粉丝馅料")
    r = client.put(f"/api/daily/{DAY}/production", json=[{**fs, "batches": "0"}])
    assert r.status_code == 400


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


def _team(day, pid):
    rows = client.get("/api/reports/cost", params={"start": day, "end": day}).json()["rows"]
    return next(r for r in rows if r["product_id"] == pid)["team"]


def test_a04_attr_change_from_date_keeps_history(demo):
    """产品班组从 10-14 起改：10-13 的报表仍是旧班组，10-14 起是新班组。"""
    prods = client.get("/api/products").json()
    p = next(x for x in prods if x["name"] == "粉丝馅料")
    old_team = p["team"]
    r = client.put(f"/api/products/{p['id']}", json={"team": "烧麦豆沙组", "attr_effective_date": "2026-10-14"})
    assert r.status_code == 200, r.text
    assert _team("2026-10-13", p["id"]) == old_team
    assert _team("2026-10-14", p["id"]) == "烧麦豆沙组"
    vers = client.get("/api/attr-versions", params={"entity": "product", "entity_id": p["id"]}).json()
    assert [v["effective_date"] for v in vers] == ["1900-01-01", "2026-10-14"]
    log = client.get("/api/change-log").json()
    assert any(x["table"] == "product" and x["row_id"] == p["id"] for x in log)


def test_a04_correction_changes_all_history(demo):
    prods = client.get("/api/products").json()
    p = next(x for x in prods if x["name"] == "粉丝馅料")
    client.put(f"/api/products/{p['id']}", json={"team": "烧麦豆沙组", "attr_effective_date": "2026-10-14"})
    client.put(f"/api/products/{p['id']}", json={"team": "拌馅组", "attr_correction": True})
    assert _team("2026-10-13", p["id"]) == "拌馅组" and _team("2026-10-14", p["id"]) == "拌馅组"


def test_a04_cooled_flag_versioned_in_engine(demo):
    """“是否制冷”从 10-14 起关掉：10-13 仍有冷后单价，10-14 没有。"""
    prods = client.get("/api/products").json()
    p = next(x for x in prods if x["name"] == "粉丝馅料")
    assert p["cooled"] is True
    client.put(f"/api/products/{p['id']}", json={"cooled": False, "attr_effective_date": "2026-10-14"})
    rows = client.get("/api/reports/cost", params={"start": "2026-10-13", "end": "2026-10-14"}).json()["rows"]
    by_day = {r["date"]: r for r in rows if r["product_id"] == p["id"]}
    assert by_day["2026-10-13"]["cooled_a"] is not None
    assert by_day["2026-10-14"]["cooled_a"] is None


def test_migrate_adds_missing_columns(tmp_path):
    from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect, text

    from app.db import migrate

    eng = create_engine(f"sqlite:///{tmp_path}/old.db")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
    md = MetaData()
    Table("t", md, Column("id", Integer, primary_key=True), Column("extra", String(10)))
    assert migrate(eng, md) == ["t.extra"]
    assert "extra" in {c["name"] for c in inspect(eng).get_columns("t")}
    assert migrate(eng, md) == []