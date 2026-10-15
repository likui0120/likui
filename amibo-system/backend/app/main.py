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
from .models import CalcEnergy, CalcIssue, CalcMaterial, CalcProduct, Product
from .upgrade import upgrade

backup.backup_before_upgrade(Base.metadata)  # 要加表/加列时先备份旧库
Base.metadata.create_all(engine)
upgrade()  # 旧数据库：先备份，补新列，重算填上；失败下次启动重试


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
    ptype = lambda c: c.ptype or prods[c.product_id].ptype  # noqa: E731
    # 差额合计只算成品馅：半成品油、麻油的差额已经通过投料单价传进下游成品，再加一次就重复了
    finals = [c for c in cps if ptype(c) == "成品馅"]
    diff = sum((c.diff_amount for c in finals if c.diff_amount is not None), start=0)
    diff_mid = sum((c.diff_amount for c in cps if ptype(c) != "成品馅" and c.diff_amount is not None), start=0)
    # 全损损失单独列，不混进差额（混进去会把“报废了”读成“差额变小”）
    mat_losses = list(db.scalars(select(CalcMaterial.loss_amount).where(
        CalcMaterial.date == d, CalcMaterial.loss_amount.is_not(None))))
    loss = sum((c.loss_amount for c in cps if c.loss_amount is not None), start=0) + sum(mat_losses, start=0)
    loss_count = sum(1 for i in issues if i.kind == "alert" and i.item_key.endswith(":loss")) + sum(
        1 for i in issues if i.kind == "alert" and i.message.startswith("全损") and i.item_key.startswith("m:"))
    quality = {}
    for c in cps:
        st = (c.quality or {}).get("status", "complete" if c.ok else "none")
        quality[st] = quality.get(st, 0) + 1
    todo = [{"name": prods[c.product_id].name, "status": (c.quality or {}).get("label"),
             "flags": (c.quality or {}).get("flags", [])[:3]}
            for c in cps if (c.quality or {}).get("status") not in (None, "complete")]
    last = db.scalar(select(func.max(CalcEnergy.date)))
    return {
        "date": d.isoformat(),
        "last_date": last.isoformat() if last else None,
        "total_output": str(energy.total_output) if energy else None,
        "products": len(cps),
        "products_ok": sum(1 for c in cps if c.ok),
        "quality": quality,
        "todo": todo,
        "alerts": sum(1 for i in issues if i.kind == "alert"),
        "warnings": sum(1 for i in issues if i.kind == "warning"),
        "diff_amount": str(diff),
        "diff_amount_mid": str(diff_mid),
        "loss_amount": str(loss),
        "loss_count": loss_count,
        "energy": energy.data["summary"] if energy else None,
        "energy_cost": energy.data.get("cost_total") if energy else None,
        "energy_complete": energy.data.get("complete") if energy else None,
        "energy_notes": energy.data.get("notes", []) if energy else [],
        "top": sorted(
            [{"name": prods[c.product_id].name, "ptype": ptype(c), "diff_amount": str(c.diff_amount),
              "diff_price": str(c.diff_price)}
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
