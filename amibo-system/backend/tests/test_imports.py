"""T+ 单价导入：各种文件格式、预览、匹配方式、覆盖提示、导入记录与撤销。"""
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Material, MaterialPrice

client = TestClient(app)
DAY = "2026-10-15"
FIX = Path(__file__).parent / "fixtures"


def post(name, content, **data):
    return client.post("/api/import/tplus", data={"day": DAY, "unit": "jin", **data},
                       files={"file": (name, content, "application/octet-stream")})


def price_of(db, name, day=DAY):
    db.expire_all()
    m = db.scalars(select(Material).where(Material.name == name)).one()
    r = db.scalars(select(MaterialPrice).where(MaterialPrice.material_id == m.id)).all()
    r = [x for x in r if x.date.isoformat() == day]
    return r[0] if r else None


def set_code(db, name, code):
    m = db.scalars(select(Material).where(Material.name == name)).one()
    m.code = code
    db.commit()


def test_xls_preview_does_not_save(demo):
    set_code(demo, "姜", "1001")
    r = post("tplus.xls", (FIX / "tplus_sample.xls").read_bytes(), preview="true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["price_col"] == "无税单价" and body["price_tax"] == "不含税"
    assert [c["name"] for c in body["price_cols"]] == ["无税单价", "含税单价"]
    items = {x["name"]: x for x in body["items"]}
    ginger = items["姜"]
    assert ginger["match"] == "编码" and ginger["rows"] == [4, 5]
    assert Decimal(ginger["price"]) == (Decimal("320") + Decimal("175")) / 150  # 按数量加权
    scallion = items["大葱"]
    assert scallion["match"] == "名称"
    assert Decimal(scallion["price"]) == Decimal("3")  # 6 元/公斤 = 3 元/斤
    assert any("涨了" in n for n in scallion["notes"])  # 示例上次 1.8 左右
    assert [u["name"] for u in body["unmatched"]] == ["不存在的料"]
    assert price_of(demo, "姜") is None  # 预览不写库


def test_choose_tax_included_column(demo):
    r = post("tplus.xls", (FIX / "tplus_sample.xls").read_bytes(), preview="true", price_col="含税单价")
    body = r.json()
    assert body["price_tax"] == "含税"
    ginger = next(x for x in body["items"] if x["name"] == "姜")
    assert Decimal(ginger["price"]) == (100 * Decimal("3.49") + 50 * Decimal("3.8")) / 150
    assert post("tplus.xls", (FIX / "tplus_sample.xls").read_bytes(), preview="true",
                price_col="不存在的列").status_code == 400


def test_commit_then_undo(demo):
    # 当天先手工填一个姜的单价，导入会覆盖并提示，撤销后恢复
    m = demo.scalars(select(Material).where(Material.name == "姜")).one()
    demo.add(MaterialPrice(material_id=m.id, date=date(2026, 10, 15), price=Decimal("9"), source="手工"))
    demo.commit()
    content = (FIX / "tplus_sample.xls").read_bytes()
    pre = post("tplus.xls", content, preview="true").json()
    ginger = next(x for x in pre["items"] if x["name"] == "姜")
    assert ginger["old_price"] == "9" and any("会覆盖" in n for n in ginger["notes"])

    r = post("tplus.xls", content)
    assert r.status_code == 200, r.text
    bid = r.json()["batch_id"]
    assert Decimal(price_of(demo, "姜").price) == Decimal("3.3")
    assert price_of(demo, "大葱").source.startswith(f"T+#{bid}")

    batches = client.get("/api/import/batches", params={"day": DAY}).json()
    assert batches[0]["id"] == bid and batches[0]["matched"] == 2 and batches[0]["unmatched"] == 1
    assert len(client.get(f"/api/import/batches/{bid}").json()["detail"]) == 2

    # 撤销前手工改了大葱，撤销时不动它
    sc = price_of(demo, "大葱")
    sc.price, sc.source = Decimal("2"), "手工"
    demo.commit()
    u = client.post(f"/api/import/batches/{bid}/undo").json()
    assert u["restored"] == ["姜"] and [s["name"] for s in u["skipped"]] == ["大葱"]
    g = price_of(demo, "姜")
    assert g.price == Decimal("9") and g.source == "手工"
    assert client.post(f"/api/import/batches/{bid}/undo").status_code == 400


def test_undo_removes_new_prices(demo):
    r = post("tplus.xls", (FIX / "tplus_sample.xls").read_bytes())
    bid = r.json()["batch_id"]
    client.post(f"/api/import/batches/{bid}/undo")
    assert price_of(demo, "姜") is None and price_of(demo, "大葱") is None


def test_gbk_csv(demo):
    text = "存货编码,存货名称,计量单位,数量,单价\r\n,姜,斤,10,4.2\r\n"
    r = post("tplus.csv", text.encode("gbk"), preview="true")
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["name"] == "姜"


def test_html_table_xls(demo):
    html = ("<html><body><table><tr><td>存货名称</td><td>计量单位</td><td>单价</td></tr>"
            "<tr><td>姜</td><td>公斤</td><td>8.4</td></tr></table></body></html>")
    r = post("export.xls", html.encode("utf-8"), preview="true")
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["items"][0]["price"]) == Decimal("4.2")


def test_code_name_conflict_and_bad_rows(demo):
    set_code(demo, "姜", "1001")
    text = ("存货编码,存货名称,计量单位,单价\n"
            "1001,大葱,斤,3\n"  # 编码是姜，名称是大葱：按编码，提示核对
            ",大蒜,箱,30\n"  # 单位换算不了
            ",大豆油,斤,0\n")  # 单价不是正数
    body = post("t.csv", text.encode("utf-8"), preview="true").json()
    item = body["items"][0]
    assert item["name"] == "姜" and item["match"] == "编码" and "另一个原料" in item["notes"][0]
    reasons = {b["name"]: b["reason"] for b in body["bad"]}
    assert "无法换算" in reasons["大蒜"] and "不是正数" in reasons["大豆油"]


def test_bad_file(demo):
    assert post("x.xlsx", b"not an excel file").status_code == 400
    assert post("x.xls", b"").status_code == 400
    assert post("x.csv", "名称,数量\n姜,1\n".encode()).status_code == 400  # 没有单价列
    # 一行都匹配不上时不能确认导入
    assert post("x.csv", "存货名称,单价\n没有这个,1\n".encode()).status_code == 400
