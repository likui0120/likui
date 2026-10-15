"""Excel 导入：T+ 单价、原料清单、产品清单、BOM。匹配失败的行列出来让人处理。"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from decimal import Decimal
from html.parser import HTMLParser

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models_import import ImportBatch
from ..models import (
    MATERIAL_CATEGORIES, PRODUCT_TYPES, TEAMS, Bom, BomLine, Material, MaterialPrice, MaterialStdYield, Product,
    ProductStdYield,
)
from .common import flush_or_400, parse_date, recalc_after

router = APIRouter(prefix="/api/import")


# ---------------------------------------------------------------- 读表

def norm(s) -> str:
    """名称归一：去空格，全角括号转半角。"""
    if s is None:
        return ""
    s = str(s).strip()
    s = s.replace("（", "(").replace("）", ")").replace("　", "")
    return re.sub(r"\s+", "", s)


OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # 旧版 .xls（Excel 97-2003）文件头


def decode_text(data: bytes) -> str:
    """中文 Windows 上 Excel 另存的 CSV 多是 GBK 编码，先试 UTF-8，不行再按 GB18030。"""
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


class _TableParser(HTMLParser):
    """有些系统导出的“.xls”其实是网页表格，按 <tr>/<td> 读出来。"""

    def __init__(self):
        super().__init__()
        self.rows, self.row, self.buf, self.in_cell = [], None, [], False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.in_cell, self.buf = True, []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.row is not None and self.in_cell:
            self.row.append("".join(self.buf).strip() or None)
            self.in_cell = False
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.in_cell:
            self.buf.append(data)


def _xls_rows(data: bytes) -> list[list]:
    try:
        import xlrd
    except ImportError:
        raise HTTPException(400, "这台电脑还没装读取 .xls 的组件（xlrd），请重新双击启动系统.bat 安装，"
                                 "或先在 Excel 里另存为 .xlsx 再上传")

    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception:
        raise HTTPException(400, "这个 .xls 文件读不出来，请在 Excel 里另存为 .xlsx 后再上传")
    sheets = [book.sheet_by_index(i) for i in range(book.nsheets)]
    sheet = next((sh for sh in sheets if sh.nrows), sheets[0] if sheets else None)
    if sheet is None:
        return []
    rows = []
    for r in range(sheet.nrows):
        out = []
        for c in sheet.row(r):
            v = c.value
            if c.ctype == xlrd.XL_CELL_NUMBER and float(v).is_integer():
                v = int(v)  # 编码列 1001 不要读成 1001.0
            elif c.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                v = None
            out.append(v)
        rows.append(out)
    return rows


def _xlsx_rows(data: bytes) -> list[list]:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise HTTPException(400, "文件无法读取，请确认是 Excel（.xlsx/.xls）或 .csv 文件")
    for ws in wb.worksheets:  # 取第一个有内容的工作表
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        if any(any(v is not None for v in r) for r in rows):
            return rows
    return []


def read_rows(upload: UploadFile) -> list[list]:
    """按文件内容判断格式（不只看扩展名）：.xlsx、旧版 .xls、网页表格、CSV。"""
    data = upload.file.read()
    if not data:
        raise HTTPException(400, "文件是空的")
    if data[:4] == b"PK\x03\x04":
        return _xlsx_rows(data)
    if data[:8] == OLE2:
        return _xls_rows(data)
    text = decode_text(data)
    head = text.lstrip()[:2000].lower()
    if head.startswith("<") and "<table" in text.lower():
        p = _TableParser()
        p.feed(text)
        return p.rows
    name = (upload.filename or "").lower()
    if name.endswith((".xlsx", ".xls", ".xlsm")):
        raise HTTPException(400, "文件无法读取，请确认是 Excel（.xlsx/.xls）或 .csv 文件")
    return [row for row in csv.reader(io.StringIO(text))]


def find_header(rows: list[list], must: list[list[str]], scan: int = 15):
    """在前几行里找表头：每组关键字至少命中一个。返回 (表头行号, {关键字组下标: 列号})。"""
    for i, row in enumerate(rows[:scan]):
        cells = [norm(c) for c in row]
        found = {}
        for gi, keys in enumerate(must):
            for ci, c in enumerate(cells):
                if c and any(k in c for k in keys):
                    found.setdefault(gi, ci)
        if len(found) == len(must):
            return i, cells
    return None, None


def col(cells: list[str], *keys, exclude=()):
    for k in keys:
        for i, c in enumerate(cells):
            if c and k in c and not any(e in c for e in exclude):
                return i
    return None


def cell(row, i):
    if i is None or i >= len(row):
        return None
    v = row[i]
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def num(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).replace(",", "").strip())
    except Exception:
        return None


def ratio(v) -> Decimal | None:
    """出率：支持 85%、0.85、85 三种写法。"""
    if v is None or v == "":
        return None
    s = str(v).strip()
    pct = s.endswith("%")
    d = num(s.rstrip("%"))
    if d is None:
        return None
    if pct or d > 10:
        d = d / 100
    return d


def yes(v) -> bool:
    return norm(v) in ("是", "Y", "y", "1", "true", "True", "需要", "√", "TRUE")


def pick_price_col(cells: list[str]):
    """单价列：优先“无税单价/不含税单价/单价”，其次含“单价”但不是含税单价的列，最后“价格”。"""
    for exact in ("无税单价", "不含税单价", "未税单价", "单价"):
        if exact in cells:
            return cells.index(exact)
    for i, c in enumerate(cells):
        if "单价" in c and not ("含税" in c and "不含税" not in c):
            return i
    return col(cells, "单价", "价格")


def tax_kind(header: str) -> str:
    if any(k in header for k in ("不含税", "无税", "未税")):
        return "不含税"
    if "含税" in header or "价税" in header:
        return "含税"
    return "未注明"


class Matcher:
    def __init__(self, db: Session):
        self.by_code = {}
        self.by_name = {}
        for m in db.scalars(select(Material)):
            if m.code:
                self.by_code[norm(m.code)] = m
            self.by_name[norm(m.name)] = m

    def find(self, code, name):
        return self.match(code, name)[0]

    def match(self, code, name):
        """返回 (原料, 匹配方式, 需要核对的说明 or None)。编码优先，其次名称。"""
        by_code = self.by_code.get(norm(code)) if code else None
        by_name = self.by_name.get(norm(name)) if name else None
        if by_code is not None:
            if by_name is not None and by_name.id != by_code.id:
                return by_code, "编码", f"编码 {code} 是“{by_code.name}”，但名称“{name}”是另一个原料，已按编码匹配，请核对"
            return by_code, "编码", None
        if by_name is not None:
            if code and by_name.code and norm(by_name.code) != norm(code):
                return by_name, "名称", f"T+ 编码 {code} 与原料资料里的编码 {by_name.code} 不一致，已按名称匹配"
            return by_name, "名称", None
        return None, None, None


# ---------------------------------------------------------------- T+ 单价

PRICE_JUMP = Decimal("0.3")  # 和上次单价相比变化超过 30% 时提示核对


def _price_cols(cells: list[str]) -> list[int]:
    return [i for i, c in enumerate(cells) if c and ("单价" in c or c == "价格") and "金额" not in c]


def parse_tplus(db: Session, d, rows: list[list], unit: str, price_col: str | None):
    """读 T+ 表，算出每个原料当天的 1 级单价（元/斤），并和已有单价比较。不写库。"""
    hi, cells = find_header(rows, [["单价", "价格"], ["名称", "编码", "编号"]])
    if hi is None:
        raise HTTPException(400, "没找到表头，请确认表里有“单价”列和“存货名称/存货编码”列")
    candidates = _price_cols(cells)
    if price_col:
        if norm(price_col) not in cells:
            raise HTTPException(400, f"表里没有“{price_col}”这一列")
        c_price = cells.index(norm(price_col))
    else:
        c_price = pick_price_col(cells)
    c_code = col(cells, "存货编码", "编码", "编号")
    c_name = col(cells, "存货名称", "名称")
    c_unit = col(cells, "计量单位", "主计量", "单位")
    c_qty = col(cells, "数量", exclude=("单价", "金额"))
    matcher = Matcher(db)
    agg: dict[int, dict] = {}
    unmatched, bad = [], []
    for ri, row in enumerate(rows[hi + 1:], start=hi + 2):
        code, name, price = cell(row, c_code), cell(row, c_name), num(cell(row, c_price))
        if not code and not name:
            continue
        if any(k in str(name or "") + str(code or "") for k in ("合计", "小计", "总计")):
            continue
        code = str(code).strip() if code is not None else None
        u = norm(cell(row, c_unit)) if c_unit is not None else ""
        u = u or ("kg" if unit == "kg" else "斤")
        if u.lower() in ("kg", "公斤", "千克"):
            factor = Decimal("0.5")  # 元/公斤 → 元/斤
        elif u in ("斤", "市斤"):
            factor = Decimal(1)
        else:
            bad.append({"row": ri, "code": code, "name": name, "reason": f"计量单位“{u}”无法换算成斤，已跳过"})
            continue
        m, how, note = matcher.match(code, name)
        if m is None:
            unmatched.append({"row": ri, "code": code, "name": name, "price": str(price) if price is not None else None})
            continue
        if price is None:
            bad.append({"row": ri, "code": code, "name": name, "reason": "单价为空"})
            continue
        if price <= 0:
            bad.append({"row": ri, "code": code, "name": name, "reason": f"单价 {price} 不是正数，已跳过"})
            continue
        a = agg.setdefault(m.id, {"m": m, "how": how, "notes": [], "rows": [], "file_names": set(),
                                  "qty": Decimal(0), "amt": Decimal(0), "prices": [], "no_qty": False})
        if note and note not in a["notes"]:
            a["notes"].append(note)
        a["rows"].append(ri)
        if name:
            a["file_names"].add(str(name).strip())
        p_jin = price * factor
        a["prices"].append(p_jin)
        q = num(cell(row, c_qty))
        if q and q > 0:
            q_jin = q / factor  # 公斤 → 斤
            a["qty"] += q_jin
            a["amt"] += q_jin * p_jin
        else:
            a["no_qty"] = True

    ids = list(agg)
    existing = {r.material_id: r for r in db.scalars(
        select(MaterialPrice).where(MaterialPrice.date == d, MaterialPrice.material_id.in_(ids)))} if ids else {}
    prev = {}
    if ids:
        sub = (select(MaterialPrice.material_id, func.max(MaterialPrice.date).label("d"))
               .where(MaterialPrice.date < d, MaterialPrice.material_id.in_(ids))
               .group_by(MaterialPrice.material_id).subquery())
        stmt = select(MaterialPrice).join(sub, (MaterialPrice.material_id == sub.c.material_id)
                                          & (MaterialPrice.date == sub.c.d))
        prev = {r.material_id: r for r in db.scalars(stmt)}

    items = []
    for mid, a in agg.items():
        m = a["m"]
        notes, info = list(a["notes"]), []  # notes 需要核对，info 只是说明
        if len(a["rows"]) > 1 and not a["no_qty"] and a["qty"]:
            price = a["amt"] / a["qty"]
            if len(set(a["prices"])) > 1:
                info.append(f"{len(a['rows'])} 行单价不同，按数量加权平均")
        else:
            price = a["prices"][-1]
            if len(set(a["prices"])) > 1:
                notes.append(f"{len(a['rows'])} 行单价不同且缺数量，取最后一行")
        old = existing.get(mid)
        pv = prev.get(mid)
        change = None
        if pv is not None and pv.price:
            change = price / pv.price - 1
            if abs(change) > PRICE_JUMP:
                hint = ""
                ratio_ = price / pv.price
                if Decimal("1.9") <= ratio_ <= Decimal("2.1") or Decimal("0.475") <= ratio_ <= Decimal("0.525"):
                    hint = "，接近 2 倍关系，可能是公斤和斤弄混了"
                notes.append(f"比上次（{pv.date.isoformat()}）{'涨' if change > 0 else '降'}了 "
                             f"{abs(change) * 100:.1f}%{hint}")
        if old is not None and old.price != price:
            if (old.source or "").startswith("T+"):
                notes.append(f"会覆盖当天之前导入的单价 {old.price}")
            else:
                notes.append(f"会覆盖当天{old.source or '已有'}填写的单价 {old.price}")
        items.append({
            "material_id": mid, "name": m.name, "code": m.code, "category": m.category,
            "file_names": sorted(a["file_names"] - {m.name}), "match": a["how"], "rows": a["rows"],
            "price": str(price), "qty": str(a["qty"]) if a["qty"] else None,
            "old_price": str(old.price) if old is not None else None,
            "old_source": old.source if old is not None else None,
            "prev_price": str(pv.price) if pv is not None else None,
            "prev_date": pv.date.isoformat() if pv is not None else None,
            "change": str(change) if change is not None else None,
            "notes": notes, "info": info,
        })
    items.sort(key=lambda x: (not x["notes"], x["rows"][0]))
    price_header = cells[c_price] if c_price is not None else None
    return {
        "header_row": hi + 1,
        "columns": {k: (cells[v] if v is not None else None) for k, v in
                    (("code", c_code), ("name", c_name), ("unit", c_unit), ("qty", c_qty), ("price", c_price))},
        "price_col": price_header,
        "price_tax": tax_kind(price_header or ""),
        "price_cols": [{"name": cells[i], "tax": tax_kind(cells[i])} for i in candidates],
        "unit_default": None if c_unit is not None else ("元/公斤" if unit == "kg" else "元/斤"),
        "items": items, "unmatched": unmatched, "bad": bad,
        "flagged": sum(1 for x in items if x["notes"]),
    }


@router.post("/tplus")
def import_tplus(day: str = Form(...), unit: str = Form("jin"), file: UploadFile = File(...),
                 preview: bool = Form(False), price_col: str | None = Form(None),
                 db: Session = Depends(get_db)):
    """导入 T+ 导出的单价表。preview=true 只预览不保存。

    自动找含“单价”和“名称/编码”的表头行。按编码优先、名称其次匹配原料。
    单价列默认优先取不含税单价，可用 price_col 指定。
    同一原料出现多行时按数量加权（Σ 数量×单价 ÷ Σ 数量），缺数量时取最后一行。
    单位：表里有“计量单位”列时按每行单位换算（公斤/千克/kg 的单价 ÷ 2），否则按所选单位。
    确认导入时记一条导入批次，可在导入记录里撤销。
    """
    d = parse_date(day)
    rows = read_rows(file)
    res = parse_tplus(db, d, rows, unit, price_col)
    res["file"] = file.filename
    if preview:
        return res
    if not res["items"]:
        raise HTTPException(400, "没有可导入的单价：没有一行匹配上原料")
    batch = ImportBatch(kind="tplus", date=d, filename=file.filename, price_col=res["price_col"],
                        matched=len(res["items"]), unmatched=len(res["unmatched"]), flagged=res["flagged"])
    db.add(batch)
    db.flush()
    src = f"T+#{batch.id}：{file.filename}"[:255]
    existing = {r.material_id: r for r in db.scalars(select(MaterialPrice).where(MaterialPrice.date == d))}
    detail = []
    for it in res["items"]:
        mid, price = it["material_id"], Decimal(it["price"])
        row = existing.get(mid)
        detail.append({"material_id": mid, "name": it["name"], "new_price": it["price"],
                       "old_price": str(row.price) if row is not None else None,
                       "old_source": row.source if row is not None else None})
        if row is None:
            db.add(MaterialPrice(material_id=mid, date=d, price=price, source=src))
        else:
            row.price, row.source = price, src
    batch.detail = detail
    flush_or_400(db)
    res["batch_id"] = batch.id
    res["recalc"] = recalc_after(db, d)
    # 旧字段，兼容之前的页面
    res["matched"] = [{"material_id": x["material_id"], "name": x["name"], "price": x["price"], "rows": len(x["rows"])}
                      for x in res["items"]]
    return res


def batch_dict(b: ImportBatch) -> dict:
    return {"id": b.id, "kind": b.kind, "date": b.date.isoformat(), "filename": b.filename,
            "created_at": b.created_at.isoformat(timespec="seconds") if b.created_at else None,
            "price_col": b.price_col, "matched": b.matched, "unmatched": b.unmatched, "flagged": b.flagged,
            "undone_at": b.undone_at.isoformat(timespec="seconds") if b.undone_at else None}


@router.get("/batches")
def list_batches(day: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    stmt = select(ImportBatch).order_by(ImportBatch.id.desc()).limit(min(max(limit, 1), 500))
    if day:
        stmt = stmt.where(ImportBatch.date == parse_date(day))
    return [batch_dict(b) for b in db.scalars(stmt)]


@router.get("/batches/{bid}")
def get_batch(bid: int, db: Session = Depends(get_db)):
    b = db.get(ImportBatch, bid)
    if b is None:
        raise HTTPException(404, "没有这条导入记录")
    return {**batch_dict(b), "detail": b.detail or []}


@router.post("/batches/{bid}/undo")
def undo_batch(bid: int, db: Session = Depends(get_db)):
    """撤销一次 T+ 导入：把这次导入写的单价恢复成导入前的值（导入前没有就删掉）。

    导入之后又被手工改过或被别的导入覆盖的原料不动，列出来。
    """
    b = db.get(ImportBatch, bid)
    if b is None:
        raise HTTPException(404, "没有这条导入记录")
    if b.undone_at is not None:
        raise HTTPException(400, "这次导入已经撤销过了")
    prefix = f"T+#{b.id}："
    current = {r.material_id: r for r in db.scalars(select(MaterialPrice).where(MaterialPrice.date == b.date))}
    restored, skipped = [], []
    for it in b.detail or []:
        row = current.get(it["material_id"])
        if row is None or not (row.source or "").startswith(prefix):
            skipped.append({"name": it["name"], "reason": "导入后已被修改或删除，没有撤销"})
            continue
        if it.get("old_price") is None:
            db.delete(row)
        else:
            row.price, row.source = Decimal(it["old_price"]), it.get("old_source")
        restored.append(it["name"])
    b.undone_at = datetime.now()
    flush_or_400(db)
    summary = recalc_after(db, b.date)
    return {"restored": restored, "skipped": skipped, "recalc": summary}


# ---------------------------------------------------------------- 原料清单

@router.post("/materials")
def import_materials(effective_date: str = Form("2020-01-01"), file: UploadFile = File(...),
                     db: Session = Depends(get_db)):
    eff = parse_date(effective_date)
    rows = read_rows(file)
    hi, cells = find_header(rows, [["名称"]])
    if hi is None:
        raise HTTPException(400, "没找到表头，至少需要“名称”列")
    c_code, c_name = col(cells, "编码", "编号"), col(cells, "名称")
    c_cat, c_proc, c_std = col(cells, "类别", "分类"), col(cells, "处理"), col(cells, "标准出率", "出率")
    matcher = Matcher(db)
    created, updated, bad = 0, 0, []
    for ri, row in enumerate(rows[hi + 1:], start=hi + 2):
        name = cell(row, c_name)
        if not name:
            continue
        code = cell(row, c_code)
        cat = norm(cell(row, c_cat)) or None
        if cat and cat not in MATERIAL_CATEGORIES:
            bad.append({"row": ri, "name": name, "reason": f"类别“{cat}”不在 {'/'.join(MATERIAL_CATEGORIES)} 中，按“其他”处理"})
            cat = "其他"
        m = matcher.find(code, name)
        if m is None:
            m = Material(name=str(name).strip(), code=str(code).strip() if code else None, category=cat or "其他")
            db.add(m)
            created += 1
        else:
            updated += 1
            if code:
                m.code = str(code).strip()
            if cat:
                m.category = cat
        if c_proc is not None and cell(row, c_proc) is not None:
            m.needs_process = yes(cell(row, c_proc))
        elif m.id is None:
            m.needs_process = cat in ("蔬菜", "泡发", "肉")
        db.flush()
        matcher.by_name[norm(m.name)] = m
        if m.code:
            matcher.by_code[norm(m.code)] = m
        std = ratio(cell(row, c_std))
        if std is not None:
            sy = db.scalars(select(MaterialStdYield).where(MaterialStdYield.material_id == m.id,
                                                           MaterialStdYield.effective_date == eff)).first()
            if sy is None:
                db.add(MaterialStdYield(material_id=m.id, effective_date=eff, std_yield=std))
            else:
                sy.std_yield = std
    flush_or_400(db)
    recalc_after(db, None)
    return {"created": created, "updated": updated, "bad": bad}


# ---------------------------------------------------------------- 产品清单

@router.post("/products")
def import_products(effective_date: str = Form("2020-01-01"), file: UploadFile = File(...),
                    db: Session = Depends(get_db)):
    eff = parse_date(effective_date)
    rows = read_rows(file)
    hi, cells = find_header(rows, [["名称"]])
    if hi is None:
        raise HTTPException(400, "没找到表头，至少需要“名称”列")
    c_code, c_name = col(cells, "编码", "编号"), col(cells, "名称")
    c_type, c_team = col(cells, "类型"), col(cells, "班组")
    c_cool, c_pack = col(cells, "是否制冷", "制冷", exclude=("出率",)), col(cells, "是否包装", "包装", exclude=("出率",))
    c_s1 = col(cells, "熟制标准出率", "拌馅标准出率", "熟制出率", "出机标准出率")
    c_s2, c_s3 = col(cells, "制冷标准出率", "制冷出率"), col(cells, "包装标准出率", "包装出率")
    existing = {norm(p.name): p for p in db.scalars(select(Product))}
    created, updated, bad = 0, 0, []
    for ri, row in enumerate(rows[hi + 1:], start=hi + 2):
        name = cell(row, c_name)
        if not name:
            continue
        p = existing.get(norm(name))
        if p is None:
            p = Product(name=str(name).strip())
            db.add(p)
            existing[norm(name)] = p
            created += 1
        else:
            updated += 1
        if cell(row, c_code):
            p.code = str(cell(row, c_code)).strip()
        t = norm(cell(row, c_type))
        if t:
            if t in PRODUCT_TYPES:
                p.ptype = t
            else:
                bad.append({"row": ri, "name": name, "reason": f"类型“{t}”无效"})
        team = norm(cell(row, c_team))
        if team:
            if team in TEAMS:
                p.team = team
            else:
                bad.append({"row": ri, "name": name, "reason": f"班组“{team}”无效"})
        if c_cool is not None and cell(row, c_cool) is not None:
            p.cooled = yes(cell(row, c_cool))
        if c_pack is not None and cell(row, c_pack) is not None:
            p.packed = yes(cell(row, c_pack))
        db.flush()
        s1, s2, s3 = ratio(cell(row, c_s1)), ratio(cell(row, c_s2)), ratio(cell(row, c_s3))
        if any(x is not None for x in (s1, s2, s3)):
            sy = db.scalars(select(ProductStdYield).where(ProductStdYield.product_id == p.id,
                                                          ProductStdYield.effective_date == eff)).first()
            if sy is None:
                sy = ProductStdYield(product_id=p.id, effective_date=eff)
                db.add(sy)
            if s1 is not None:
                sy.cook_yield = s1
            if s2 is not None:
                sy.cool_yield = s2
            if s3 is not None:
                sy.pack_yield = s3
    flush_or_400(db)
    recalc_after(db, None)
    return {"created": created, "updated": updated, "bad": bad}


# ---------------------------------------------------------------- BOM

@router.post("/boms")
def import_boms(effective_date: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    """导入 BOM：每行一个投料，列：产品、投料、数量（斤/锅），可选 行号、产品编码、投料编码。

    同一产品同一生效日期已有 BOM 时整份替换。任一投料匹配不上的产品整份跳过，列出来处理。
    """
    eff = parse_date(effective_date)
    rows = read_rows(file)
    hi, cells = find_header(rows, [["产品", "成品", "馅料"], ["投料", "原料", "物料", "子件"], ["数量", "用量"]])
    if hi is None:
        raise HTTPException(400, "没找到表头，需要“产品”“投料”“数量”三列")
    c_pcode = col(cells, "产品编码", "成品编码")
    c_prod = col(cells, "产品名称", "产品", "成品名称", "成品", "馅料", exclude=("编码",))
    c_mcode = col(cells, "投料编码", "原料编码", "物料编码", "子件编码")
    c_mat = col(cells, "投料名称", "投料", "原料名称", "原料", "物料名称", "子件名称", exclude=("编码", "类型"))
    c_qty = col(cells, "数量", "用量")
    c_line = col(cells, "行号", "序号")
    matcher = Matcher(db)
    prods = {norm(p.name): p for p in db.scalars(select(Product))}
    prods_code = {norm(p.code): p for p in prods.values() if p.code}
    groups: dict[str, dict] = {}
    unmatched = []
    current_prod = None
    for ri, row in enumerate(rows[hi + 1:], start=hi + 2):
        pname = cell(row, c_prod) or current_prod  # 合并单元格时产品名只出现在第一行
        mname, qty = cell(row, c_mat), num(cell(row, c_qty))
        if not mname:
            continue
        current_prod = pname
        if not pname:
            unmatched.append({"row": ri, "product": None, "input": mname, "reason": "缺产品名称"})
            continue
        if qty is None:
            unmatched.append({"row": ri, "product": pname, "input": mname, "reason": "数量无效"})
            continue
        p = prods_code.get(norm(cell(row, c_pcode))) if cell(row, c_pcode) else None
        p = p or prods.get(norm(pname))
        g = groups.setdefault(norm(pname), {"name": pname, "product": p, "lines": [], "errors": []})
        if p is None:
            g["errors"].append({"row": ri, "product": pname, "input": mname, "reason": "产品不存在，请先在产品资料里新增"})
            continue
        m = matcher.find(cell(row, c_mcode), mname)
        up = prods.get(norm(mname)) if m is None else None
        if m is None and (up is None or up.ptype not in ("半成品油", "麻油")):
            g["errors"].append({"row": ri, "product": pname, "input": mname, "reason": "投料在原料资料里找不到"})
            continue
        line_no = int(num(cell(row, c_line)) or len(g["lines"]) + 1)
        g["lines"].append({"line_no": line_no, "material_id": m.id if m else None,
                           "input_product_id": up.id if (m is None and up) else None, "qty": qty})
    imported = []
    for g in groups.values():
        if g["errors"] or g["product"] is None:
            unmatched.extend(g["errors"] or [{"product": g["name"], "reason": "产品不存在"}])
            continue
        p = g["product"]
        b = db.scalars(select(Bom).where(Bom.product_id == p.id, Bom.effective_date == eff)).first()
        if b is None:
            b = Bom(product_id=p.id, effective_date=eff, note=f"导入：{file.filename}")
            db.add(b)
        b.lines.clear()
        for l in g["lines"]:
            b.lines.append(BomLine(**l))
        imported.append({"product": p.name, "lines": len(g["lines"]), "total": str(sum(l["qty"] for l in g["lines"]))})
    flush_or_400(db)
    recalc_after(db, eff)
    return {"imported": imported, "unmatched": unmatched}


# ---------------------------------------------------------------- 模板

TEMPLATES = {
    "materials": ("原料导入模板", ["编码", "名称", "类别", "是否需要处理", "标准出率"],
                  [["", "姜", "蔬菜", "是", "85%"], ["", "红薯粉条", "泡发", "是", "260%"], ["", "大豆油", "调料", "否", ""]]),
    "products": ("产品导入模板", ["编码", "名称", "类型", "班组", "是否制冷", "是否包装", "熟制标准出率", "制冷标准出率", "包装标准出率"],
                 [["", "粉丝馅料", "成品馅", "热加工", "是", "是", "95%", "98%", "99.5%"]]),
    "boms": ("BOM导入模板", ["产品", "行号", "投料", "数量"],
             [["粉丝馅料", 1, "肥膘", 32.829027], ["粉丝馅料", 2, "大豆油", 36.7]]),
    "tplus": ("T+单价样例", ["存货编码", "存货名称", "计量单位", "数量", "单价", "金额"],
              [["", "姜", "斤", 100, 3.2, 320]]),
}


@router.get("/template/{name}")
def template(name: str):
    if name not in TEMPLATES:
        raise HTTPException(404, "没有这个模板")
    title, header, sample = TEMPLATES[name]
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(header)
    for r in sample:
        ws.append(r)
    for i in range(1, len(header) + 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = 16
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from urllib.parse import quote
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(title)}.xlsx"})

