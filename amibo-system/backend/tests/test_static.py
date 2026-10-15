"""前端静态文件：只能拿到 dist 里的文件；写错的接口地址返回 404 而不是首页。"""
from fastapi.testclient import TestClient

from app.main import DIST, app

client = TestClient(app)


def test_static_files_cannot_escape_dist():
    if not DIST.exists():
        return
    spa = next(r for r in app.routes if getattr(r, "name", "") == "spa").endpoint
    # 局域网里有人请求 /../../data/amibo.db 这类路径时，只能拿到首页，拿不到 dist 以外的文件
    for raw in ("../../backend/app/db.py", "../../data/amibo.db", "..\\..\\backend\\app\\db.py"):
        assert spa(raw).path == DIST / "index.html"
    assert spa("index.html").path.name == "index.html"


def test_unknown_api_is_404():
    if not DIST.exists():
        return
    assert client.get("/api/no-such-api").status_code == 404
