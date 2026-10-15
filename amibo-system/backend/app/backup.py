"""数据库自动备份。

所有数据都在 data/amibo.db 一个文件里。系统开着时每天自动备份一次（启动时当天还没备份就马上备份），
存到 data/backups/，保留最近 30 份自动备份；也可以在“系统设置”里手动备份、下载备份、恢复到某个备份。
可以再设一个“另存目录”（U 盘、网盘同步文件夹等），每次备份同时复制一份过去，防止这台电脑硬盘坏了数据全丢。

用 SQLite 的在线备份接口复制，系统开着、有人在录入时也能备份，得到的是一致的快照。
恢复前会先把当前数据备份一份（before-restore），恢复错了还能再恢复回来。
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from .db import DATA_DIR, engine

log = logging.getLogger("amibo.backup")

BACKUP_DIR = DATA_DIR / "backups"
CONFIG_FILE = DATA_DIR / "backup.json"
KEEP_AUTO = 30  # 自动备份保留份数
KEEP_MANUAL = 30  # 手动备份、恢复前备份保留份数
CHECK_EVERY = 30 * 60  # 后台每 30 分钟看一次今天备份了没有
NAME_RE = re.compile(r"^amibo-(\d{8})-(\d{6})-(auto|manual|before-restore|before-upgrade)\.db$")
REASONS = {"auto": "自动", "manual": "手动", "before-restore": "恢复前", "before-upgrade": "升级前"}

_lock = threading.Lock()
router = APIRouter(prefix="/api/backups")


def db_path() -> Path | None:
    """当前数据库文件路径；不是文件型 SQLite（比如测试用内存库）时返回 None。"""
    if engine.url.get_backend_name() != "sqlite":
        return None
    db = engine.url.database
    if not db or db == ":memory:":
        return None
    return Path(db).resolve()


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    return {"extra_dir": cfg.get("extra_dir") or ""}


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _copy_db(src_path: Path, dst_path: Path, standalone: bool = True):
    """SQLite 在线备份：源库开着、有写入也能得到一致快照。

    standalone=True 时把备份文件改成普通（非 WAL）模式，单个文件就是完整备份，拷走即可用。
    """
    src = sqlite3.connect(str(src_path))
    try:
        dst = sqlite3.connect(str(dst_path))
        try:
            src.backup(dst)
            if standalone:
                dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
    finally:
        src.close()


def _info(p: Path) -> dict:
    m = NAME_RE.match(p.name)
    st = p.stat()
    created = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S") if m else datetime.fromtimestamp(st.st_mtime)
    reason = m.group(3) if m else "manual"
    return {"name": p.name, "size": st.st_size, "created_at": created.isoformat(timespec="seconds"),
            "reason": reason, "reason_text": REASONS.get(reason, reason)}


def list_backups() -> list[dict]:
    if not BACKUP_DIR.exists():
        return []
    files = [p for p in BACKUP_DIR.iterdir() if p.is_file() and NAME_RE.match(p.name)]
    return sorted((_info(p) for p in files), key=lambda x: x["name"], reverse=True)


def _prune():
    groups: dict[str, list[Path]] = {}
    for p in BACKUP_DIR.iterdir():
        m = NAME_RE.match(p.name)
        if m:
            groups.setdefault("auto" if m.group(3) == "auto" else "other", []).append(p)
    for g, files in groups.items():
        keep = KEEP_AUTO if g == "auto" else KEEP_MANUAL
        for p in sorted(files, key=lambda x: x.name, reverse=True)[keep:]:
            try:
                p.unlink()
            except OSError:
                log.warning("删除旧备份失败：%s", p)


def make_backup(reason: str = "manual") -> dict:
    """备份一份，返回备份信息；另存目录复制失败不影响本地备份，结果里带上原因。"""
    src = db_path()
    if src is None or not src.exists():
        raise HTTPException(400, "找不到数据库文件，无法备份")
    with _lock:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        while True:
            dst = BACKUP_DIR / f"amibo-{datetime.now():%Y%m%d-%H%M%S}-{reason}.db"
            if not dst.exists():
                break
            time.sleep(0.3)  # 同一秒内连点两次，等到下一秒
        tmp = dst.with_suffix(".tmp")
        _copy_db(src, tmp)
        tmp.replace(dst)
        info = _info(dst)
        extra = load_config()["extra_dir"]
        if extra:
            try:
                Path(extra).mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, Path(extra) / dst.name)
                info["extra"] = str(Path(extra) / dst.name)
            except OSError as e:
                info["extra_error"] = f"复制到另存目录失败：{e}"
                log.warning("复制备份到 %s 失败：%s", extra, e)
        _prune()
        return info


def backed_up_today() -> bool:
    today = datetime.now().strftime("%Y%m%d")
    return any(b["name"].startswith(f"amibo-{today}-") for b in list_backups())


def auto_backup_once():
    """今天还没有任何备份就备份一份（有数据库文件时）。"""
    try:
        if db_path() is not None and db_path().exists() and not backed_up_today():
            info = make_backup("auto")
            log.info("自动备份：%s", info["name"])
    except Exception:  # 备份失败不能影响系统运行
        log.exception("自动备份失败")


def backup_before_upgrade(metadata) -> str | None:
    """新版程序要给旧数据库加表或加列时，先备份一份（升级前），升级出问题可以恢复。返回备份文件名。"""
    try:
        src = db_path()
        if src is None or not src.exists():
            return None
        from sqlalchemy import inspect

        insp = inspect(engine)
        existing = set(insp.get_table_names())
        if not existing:
            return None  # 新库，不用备份
        for t in metadata.sorted_tables:
            if t.name not in existing or {c.name for c in t.columns} - {c["name"] for c in insp.get_columns(t.name)}:
                name = make_backup("before-upgrade")["name"]
                log.info("升级前备份：%s", name)
                return name
    except Exception:  # 备份失败不能挡住启动
        log.exception("升级前备份失败")
    return None


_stop = threading.Event()


def start_auto_backup():
    """启动时备份一次，之后每 30 分钟检查一次（跨过零点就会备份新的一天）。"""
    _stop.clear()

    def loop():
        while True:
            auto_backup_once()
            if _stop.wait(CHECK_EVERY):
                return

    threading.Thread(target=loop, name="amibo-backup", daemon=True).start()


def stop_auto_backup():
    _stop.set()


def _backup_file(name: str) -> Path:
    if not NAME_RE.match(name):
        raise HTTPException(400, "备份文件名不对")
    p = BACKUP_DIR / name
    if not p.is_file():
        raise HTTPException(404, "没有这个备份")
    return p


# ---------------------------------------------------------------- 接口

@router.get("")
def api_list():
    src = db_path()
    return {
        "backups": list_backups(),
        "dir": str(BACKUP_DIR),
        "db_file": str(src) if src else None,
        "db_size": src.stat().st_size if src and src.exists() else None,
        "keep_auto": KEEP_AUTO,
        **load_config(),
    }


@router.post("")
def api_backup():
    return make_backup("manual")


@router.put("/config")
def api_config(payload: dict = Body(...)):
    extra = str(payload.get("extra_dir") or "").strip().strip('"')
    if extra:
        p = Path(extra)
        if not p.is_absolute():
            raise HTTPException(400, "另存目录要写完整路径，例如 E:\\Amibo备份")
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".amibo-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as e:
            raise HTTPException(400, f"另存目录不能写入：{e}")
    save_config({"extra_dir": extra})
    return load_config()


@router.get("/{name}/download")
def api_download(name: str):
    p = _backup_file(name)
    return FileResponse(p, media_type="application/octet-stream", filename=p.name)


@router.post("/{name}/restore")
def api_restore(name: str):
    """把数据库恢复成某个备份。先自动备份当前数据，再用在线备份接口整库覆盖。"""
    p = _backup_file(name)
    dst_path = db_path()
    if dst_path is None:
        raise HTTPException(400, "找不到数据库文件，无法恢复")
    try:
        chk = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            ok = chk.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            chk.close()
    except sqlite3.DatabaseError:
        ok = False
    if not ok:
        raise HTTPException(400, "这个备份文件已损坏，不能恢复")
    before = make_backup("before-restore")
    with _lock:
        engine.dispose()  # 先关掉连接池里的连接，恢复后重新连接
        _copy_db(p, dst_path, standalone=False)
        engine.dispose()
    return {"restored": name, "before": before["name"]}
