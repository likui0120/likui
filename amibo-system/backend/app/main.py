"""程序入口：接口 + 前端静态页面。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import backup
from .api import daily, imports, master, reports
from .api.common import parse_date
from .db import Base, engine, get_db
from .models import CalcEnergy, CalcIssue, CalcProduct, Product

Base.metadata.create_all(engine)


@asynccontextmanager
async def lifespan(_app):
    backup.start_auto_backup()  # 启动时当天还没备份就备份一份，之后每天一份
    yield
    backup.stop_auto_backup()


app = FastAPI(title="车间出率与成本核算系统", lifespan=lifespan)
app.include_router(master.router)
app.include_router(daily.router)
app.include_router(imports.router)
app.include_router(reports.router)
app.include_router(backup.router)


@app.exception_handler(Exception)
async def on_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": f"服务器出错：{exc}"})


@app.get("/api/dashboard")
def dashboard(day: str, db: Session = Depends(get_db)):
    d = parse_date(day)
    energy = db.get(CalcEnergy, d)
    prods = {p.id: p for p in db.scalars(select(Product))}
    cps = list(db.scalars(select(CalcProduct).where(CalcProduct.date == d)))
    issues = list(db.scalars(select(CalcIssue).where(CalcIssue.date == d)))
    diff = sum((c.diff_amount for c in cps if c.diff_amount is not None), start=0)
    last = db.scalar(select(func.max(CalcEnergy.date)))
    return {
        "date": d.isoformat(),
        "last_date": last.isoformat() if last else None,
        "total_output": str(energy.total_output) if energy else None,
        "products": len(cps),
        "products_ok": sum(1 for c in cps if c.ok),
        "alerts": sum(1 for i in issues if i.kind == "alert"),
        "warnings": sum(1 for i in issues if i.kind == "warning"),
        "diff_amount": str(diff),
        "energy": energy.data["summary"] if energy else None,
        "energy_cost": energy.data.get("cost_total") if energy else None,
        "top": sorted(
            [{"name": prods[c.product_id].name, "diff_amount": str(c.diff_amount), "diff_price": str(c.diff_price)}
             for c in cps if c.diff_amount is not None],
            key=lambda x: -abs(float(x["diff_amount"])))[:5],
    }


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
DIST_ROOT = DIST.resolve()
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "没有这个接口"})
        f = (DIST / path).resolve()
        # 只给 dist 目录里的文件，防止用 ../ 读到数据库等其他文件
        if path and f.is_file() and DIST_ROOT in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
