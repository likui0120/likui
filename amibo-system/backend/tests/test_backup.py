"""数据库备份：手动备份、下载、另存目录、自动备份每天一份、保留份数、恢复与恢复前备份。"""
import sqlite3

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import backup
from app.main import app
from app.models import Material

client = TestClient(app)


def clean():
    if backup.BACKUP_DIR.exists():
        for p in backup.BACKUP_DIR.iterdir():
            p.unlink()
    if backup.CONFIG_FILE.exists():
        backup.CONFIG_FILE.unlink()


def test_manual_backup_and_download(demo):
    clean()
    r = client.post("/api/backups")
    assert r.status_code == 200, r.text
    name = r.json()["name"]
    assert name.endswith("-manual.db")
    listing = client.get("/api/backups").json()
    assert [b["name"] for b in listing["backups"]] == [name] and listing["db_size"] > 0
    con = sqlite3.connect(backup.BACKUP_DIR / name)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "delete"  # 单个文件就是完整备份
    assert con.execute("select count(*) from material").fetchone()[0] > 0
    con.close()
    d = client.get(f"/api/backups/{name}/download")
    assert d.status_code == 200 and d.content[:15] == b"SQLite format 3"
    assert client.get("/api/backups/test.db/download").status_code == 400
    assert client.post("/api/backups/x.db/restore").status_code == 400


def test_extra_dir(demo, tmp_path):
    clean()
    assert client.put("/api/backups/config", json={"extra_dir": "相对路径"}).status_code == 400
    target = tmp_path / "U盘备份"
    assert client.put("/api/backups/config", json={"extra_dir": str(target)}).json()["extra_dir"] == str(target)
    info = client.post("/api/backups").json()
    assert (target / info["name"]).exists()
    client.put("/api/backups/config", json={"extra_dir": ""})


def test_auto_once_per_day_and_prune(demo):
    clean()
    backup.auto_backup_once()
    backup.auto_backup_once()
    assert [b["reason"] for b in backup.list_backups()] == ["auto"]
    # 造 35 份旧的自动备份，再备份一次后只留最近 30 份
    for i in range(35):
        (backup.BACKUP_DIR / f"amibo-202501{i % 28 + 1:02d}-{i:06d}-auto.db").write_bytes(b"")
    backup.make_backup("auto")
    autos = [b for b in backup.list_backups() if b["reason"] == "auto"]
    assert len(autos) == backup.KEEP_AUTO
    assert autos[0]["created_at"].startswith(str(__import__("datetime").date.today()))


def test_restore(demo):
    clean()
    name = client.post("/api/backups").json()["name"]
    demo.add(Material(name="备份后新增的料", category="蔬菜"))
    demo.commit()
    r = client.post(f"/api/backups/{name}/restore")
    assert r.status_code == 200, r.text
    before = r.json()["before"]
    assert before.endswith("-before-restore.db")
    demo.rollback()
    demo.expire_all()
    names = demo.scalars(select(Material.name)).all()
    assert "备份后新增的料" not in names
    # 恢复错了可以用“恢复前”备份再恢复回来
    demo.close()
    assert client.post(f"/api/backups/{before}/restore").status_code == 200
    assert "备份后新增的料" in [m["name"] for m in client.get("/api/materials").json()]
    # 恢复后系统照常能写
    assert client.post("/api/backups").status_code == 200


def test_corrupt_backup_rejected(demo):
    clean()
    backup.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    bad = backup.BACKUP_DIR / "amibo-20260101-000000-manual.db"
    bad.write_bytes(b"not a database" * 100)
    assert client.post(f"/api/backups/{bad.name}/restore").status_code == 400

