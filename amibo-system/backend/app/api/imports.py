"""Excel 导入：T+ 单价、原料清单、产品清单、BOM。匹配失败的行列出来让人处理。"""
from __future__ import annotations

import csv
import io
import re
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    MATERIAL_CATEGORIES, PRODUCT_TYPES, TEAMS, Bom, BomLine, Material, MaterialPrice, MaterialStdYield, Product,
    ProductStdYield,
)
from .common import commit_or_400, parse_date, recalc_after

router = APIRouter(prefix="/api/import")


# ---------------------------------------------------------------- 读表

def norm(s) -> str:
    """名称归一：去空格，全角括号转半角。"""
    if s is None:
        return ""
    s = str(s).strip()
    s = s.replace("（", "(").replace("）", ")").replace("　", "")
    return re.sub(r"\s+", "", s)


def read_rows(upload: UploadFile) -> list[list]:
    data = upload.file.read()
    name = (upload.filename or "").lower()
    if name.endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        return [row for row in csv.reader(io.StringIO(text))]
    if name.endswith(".xls"):
        raise HTTPException(400, "暂不支持旧版 .xls 文件，请在 Excel 里另存为 .xlsx 后再上传")
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise HTTPException(400, "文件无法读取，请确认是 .xlsx 或 .csv 文件")
    ws = wb.worksheets[0]
    return [list(r) for r in ws.iter_rows(values_only=True)]


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
    for exact in ("无税单价", "不含税单价", "单价"):
        if exact in cells:
            return cells.index(exact)
    for i, c in enumerate(cells):
        if "单价" in c and not ("含税" in c and "不含税" not in c):
            return i
    return col(cells, "单价", "价格")


class Matcher:
    def __init__(self, db: Session):
        self.by_code = {}
        self.by_name = {}
        for m in db.scalars(select(Material)):
            if m.code:
                self.by_code[norm(m.code)] = m
            self.by_name[norm(m.name)] = m

    def find(self, code, name):
        if code and norm(code) in self.by_code:
            return self.by_code[norm(code)]
        if name and norm(name) in self.by_name:
            return self.by_name[norm(name)]
        return None


# ---------------------------------------------------------------- T+ 单价

@router.post("/tplus")
def import_tplus(day: str = Form(...), unit: str = Form("jin"), file: UploadFile = File(...),
                 db: Session = Depends(get_db)):
    """导入 T+ 导出的单价表。

    自动找含“单价”和“名称/编码”的表头行。按编码优先、名称其次匹配原料。
    同一原料出现多行时，有数量和金额列就按 Σ金额 ÷ Σ数量 加权，否则取最后一行。
    单位：表里有“计量单位”列时按每行单位换算（公斤/千克/kg ÷ 2），否则按所选单位。
    """
    d = parse_date(day)
    rows = read_rows(file)
    hi, cells = find_header(rows, [["单价", "价格"], ["名称", "编码", "编号"]])
    if hi is None:
        raise HTTPException(400, "没找到表头，请确认表里有“单价”列和“存货名称/存货编码”列")
    c_price = pick_price_col(cells)
    c_code = col(cells, "存货编码", "编码", "编号")
    c_name = col(cells, "存货名称", "名称")
    c_unit = col(cells, "计量单位", "单位")
    c_qty = col(cells, "数量")
    c_amt = col(cells, "金额", exclude=("税额",))
    matcher = Matcher(db)
    agg: dict[int, dict] = {}
    unmatched, bad = [], []
    for ri, row in enumerate(rows[hi + 1:], start=hi + 2):
        code, name, price = cell(row, c_code), cell(row, c_name), num(cell(row, c_price))
        if not code and not name:
            continue
        if name and ("合计" in str(name) or "小计" in str(name)):
            continue
        u = norm(cell(row, c_unit)) if c_unit is not None else ("kg" if unit == "kg" else "斤")
        factor = Decimal("0.5") if u.lower() in ("kg", "公斤", "千克") else Decimal(1)
        if u and u not in ("斤", "kg", "KG", "Kg", "公斤", "千克") and c_unit is not None:
            bad.append({"row": ri, "code": code, "name": name, "reason": f"计量单位“{u}”无法换算成斤，已跳过"})
            continue
        m = matcher.find(code, name)
        if m is None:
            unmatched.append({"row": ri, "code": code, "name": name, "price": str(price) if price is not None else None})
            continue
        if price is None:
            bad.append({"row": ri, "code": code, "name": name, "reason": "单价为空"})
            continue
        a = agg.setdefault(m.id, {"m": m, "rows": 0, "qty": Decimal(0), "amt": Decimal(0), "last": None})
        a["rows"] += 1
        a["last"] = price * factor
        q, amt = num(cell(row, c_qty)), num(cell(row, c_amt))
        if q and amt is not None:
            a["qty"] += q / factor  # 换成斤
            a["amt"] += amt
    existing = {r.material_id: r for r in db.scalars(select(MaterialPrice).where(MaterialPrice.date == d))}
    matched = []
    for mid, a in agg.items():
        price = a["amt"] / a["qty"] if a["rows"] > 1 and a["qty"] else a["last"]
        row = existing.get(mid)
        src = f"T+:{file.filename}"
        if row is None:
            db.add(MaterialPrice(material_id=mid, date=d, price=price, source=src))
        else:
            row.price, row.source = price, src
        matched.append({"material_id": mid, "name": a["m"].name, "price": str(price), "rows": a["rows"]})
    commit_or_400(db)
    summary = recalc_after(db, d)
    return {"matched": matched, "unmatched": unmatched, "bad": bad, "recalc": summary}


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
    commit_or_400(db)
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
    commit_or_400(db)
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
    commit_or_400(db)
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

