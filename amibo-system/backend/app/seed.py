"""初始化数据。

python -m app.seed          初始化计量表、能源单价、包装规格，以及需求文档附录里的两个 BOM
python -m app.seed --demo   另外加入示例单价、标准出率和 3 天的示例录入，用来试用（数值都是假的）
python -m app.seed --reset  清空数据库后重新初始化（慎用）
"""
import argparse
from datetime import date, timedelta
from decimal import Decimal as D

from sqlalchemy import select

from .calc.engine import recalc_from
from .db import Base, SessionLocal, engine
from .models import (
    Bom, BomLine, DailyCooling, DailyMaterialProcess, DailyPacking, DailyPackingBag, DailyProduction, EnergyPrice,
    Material, MaterialPrice, MaterialStdYield, Meter, MeterReading, MeterVersion, PackSpec, PackSpecVersion, Product,
    ProductStdYield, SeasoningPrice,
)

BASE_DATE = date(2020, 1, 1)

# 需求文档「能耗抄表与吨能耗」表：(能源, 名称, 方式, 倍率, 倍率说明, 全厂, 车间, 备注)
METERS = [
    ("gas", "大锅区域", "reading", "1", "×1", "+", "", None),
    ("gas", "小锅区域", "reading", "1", "×1", "+", "", None),
    ("gas", "豆沙区域", "reading", "1", "×1", "+", "", None),
    ("gas", "食堂区域", "reading", "1", "×1", "+", "", None),
    ("gas", "锅炉房 1#", "reading", "1", "×1", "+", "", None),
    ("gas", "锅炉房 2#", "reading", "1", "×1", "+", "", None),
    ("gas", "研发室", "reading", "1", "×1", "ref", "", "现表未计入，待确认"),
    ("gas", "储福记", "reading", "0.08", "÷1000×80", "-", "", "换算含义待确认"),
    ("water", "和善园", "reading", "1", "×1", "+", "", None),
    ("water", "工厂井水", "reading", "1", "×1", "+", "+", "井水是否计费待确认"),
    ("water", "储#1", "reading", "1", "×1", "-", "", None),
    ("water", "物流洗车区", "reading", "1", "×1", "-", "", None),
    ("water", "水站总表", "reading", "1", "×1", "", "+", "墙上水管，不含软管"),
    ("water", "洗筐区总表", "reading", "1", "×1", "", "+", "含生加工、洗筐间"),
    ("water", "生加工（单独）", "reading", "1", "×1", "ref", "ref", None),
    ("water", "洗筐间（单独）", "reading", "1", "×1", "ref", "ref", None),
    ("water", "锅炉房", "reading", "1", "×1", "ref", "", None),
    ("elec", "和善园 #1", "reading", "2000", "×2000", "+", "", None),
    ("elec", "光伏发电（正向）", "direct", "1", "直接填当日发电量", "+", "", None),
    ("elec", "储#1", "reading", "120", "×120", "-", "", None),
    ("elec", "储#2", "reading", "1", "×1", "-", "", None),
    ("elec", "榨油车间", "reading", "40", "×40", "ref", "", None),
    ("elec", "OEM 库 1", "reading", "40", "×40", "ref", "", None),
    ("elec", "OEM 库 2", "reading", "40", "×40", "ref", "", None),
    ("elec", "原料库", "reading", "40", "×40", "ref", "", None),
]

ENERGY_PRICES = {"water": "4.49", "elec": "0.8644", "gas": "4.3741"}

# (名称, 类别, 是否需要 1→2 级处理)
MATERIALS = [
    ("肥膘", "肉", True), ("大豆油", "调料", False), ("辣椒粉", "调料", False), ("大蒜", "蔬菜", True),
    ("大葱", "蔬菜", True), ("姜", "蔬菜", True), ("辣椒酱", "调料", False), ("酿造酱油（含焦糖色）", "调料", False),
    ("粉丝馅料干调", "干调", False), ("生活饮用水", "水", False), ("老豆腐丁", "其他", True), ("红薯粉条", "泡发", True),
    ("蛋白鲜肉馅干调", "干调", False), ("老抽", "调料", False), ("葱", "蔬菜", True), ("冻 2 号", "肉", True),
    ("水", "水", False), ("大豆蛋白", "调料", False), ("芝麻", "芝麻", False),
]

# 附录 BOM 样例（斤/锅）
BOMS = {
    "粉丝馅料": [("肥膘", "32.829027"), ("大豆油", "36.7"), ("辣椒粉", "2.5"), ("大蒜", "8"), ("大葱", "8"), ("姜", "5"),
                ("辣椒酱", "13.44"), ("酿造酱油（含焦糖色）", "5"), ("酿造酱油（含焦糖色）", "2.5"),
                ("粉丝馅料干调", "17.2"), ("生活饮用水", "15"), ("老豆腐丁", "80"), ("红薯粉条", "100")],
    "蛋白鲜肉馅料": [("肥膘", "509"), ("蛋白鲜肉馅干调", "133.1"), ("老抽", "36.9"), ("姜", "56.8"), ("葱", "77"),
                  ("冻 2 号", "610"), ("水", "260"), ("大豆蛋白", "210")],
}

PACK_SPECS = [("2斤袋", "2"), ("5斤袋", "5"), ("15斤袋", "15"), ("20斤袋", "20")]


def get_or_create(db, model, defaults=None, **keys):
    row = db.scalars(select(model).filter_by(**keys)).first()
    if row is None:
        row = model(**keys, **(defaults or {}))
        db.add(row)
        db.flush()
    return row


def init_base(db):
    for i, (energy, name, mode, factor, ftext, plant, ws, note) in enumerate(METERS):
        m = get_or_create(db, Meter, {"sort": i}, energy=energy, name=name)
        get_or_create(db, MeterVersion, {"mode": mode, "factor": D(factor), "factor_text": ftext, "plant": plant,
                                         "workshop": ws, "active": True, "note": note},
                      meter_id=m.id, effective_date=BASE_DATE)
    for e, p in ENERGY_PRICES.items():
        get_or_create(db, EnergyPrice, {"price": D(p)}, energy=e, effective_date=BASE_DATE)
    for i, (name, w) in enumerate(PACK_SPECS):
        s = get_or_create(db, PackSpec, {"sort": i}, name=name)
        get_or_create(db, PackSpecVersion, {"bag_weight": D(w), "fee": D(0)}, spec_id=s.id, effective_date=BASE_DATE)
    mats = {}
    for name, cat, proc in MATERIALS:
        mats[name] = get_or_create(db, Material, {"category": cat, "needs_process": proc}, name=name)
    p1 = get_or_create(db, Product, {"ptype": "成品馅", "team": "热加工", "cooled": True, "packed": True, "sort": 1},
                       name="粉丝馅料")
    p2 = get_or_create(db, Product, {"ptype": "成品馅", "team": "拌馅组", "cooled": False, "packed": True, "sort": 2},
                       name="蛋白鲜肉馅料")
    get_or_create(db, Product, {"ptype": "麻油", "team": "麻油车间", "cooled": False, "packed": False, "sort": 90,
                                "source_material_id": mats["芝麻"].id}, name="麻油")
    for p in (p1, p2):
        if db.scalars(select(Bom).where(Bom.product_id == p.id)).first() is None:
            b = Bom(product_id=p.id, effective_date=BASE_DATE, note="需求文档附录样例")
            for i, (mname, qty) in enumerate(BOMS[p.name], start=1):
                b.lines.append(BomLine(line_no=i, material_id=mats[mname].id, qty=D(qty)))
            db.add(b)
    db.flush()


# ---------------------------------------------------------------- 示例数据

DEMO_STD = {"肥膘": "0.95", "大蒜": "0.85", "大葱": "0.80", "葱": "0.80", "姜": "0.85", "老豆腐丁": "0.98",
            "红薯粉条": "2.60", "冻 2 号": "0.97"}
DEMO_PRICE = {"肥膘": "6.80", "大豆油": "4.60", "辣椒粉": "12.00", "大蒜": "3.20", "大葱": "1.80", "姜": "4.50",
              "辣椒酱": "6.00", "酿造酱油（含焦糖色）": "3.10", "老豆腐丁": "2.20", "红薯粉条": "5.50", "老抽": "3.40",
              "葱": "1.60", "冻 2 号": "9.20", "大豆蛋白": "4.80", "芝麻": "9.50"}
DEMO_FEES = {"2斤袋": "0.35", "5斤袋": "0.55", "15斤袋": "1.20", "20斤袋": "1.50"}


def init_demo(db):
    mats = {m.name: m for m in db.scalars(select(Material))}
    prods = {p.name: p for p in db.scalars(select(Product))}
    specs = {s.name: s for s in db.scalars(select(PackSpec))}
    for name, v in DEMO_STD.items():
        get_or_create(db, MaterialStdYield, {"std_yield": D(v)}, material_id=mats[name].id, effective_date=BASE_DATE)
    for name, fee in DEMO_FEES.items():
        ver = db.scalars(select(PackSpecVersion).where(PackSpecVersion.spec_id == specs[name].id)).first()
        ver.fee = D(fee)
    get_or_create(db, SeasoningPrice, {"price": D("6.50")}, material_id=mats["粉丝馅料干调"].id, effective_date=BASE_DATE)
    get_or_create(db, SeasoningPrice, {"price": D("5.80")}, material_id=mats["蛋白鲜肉馅干调"].id, effective_date=BASE_DATE)

    # 示例：半成品油 + 用到半成品油和麻油的馅料，演示跨天取价
    oil = get_or_create(db, Product, {"ptype": "半成品油", "team": "热加工", "cooled": True, "packed": False, "sort": 50,
                                      "fallback_price": D("6.00"), "note": "示例产品"}, name="葱油（示例）")
    demo = get_or_create(db, Product, {"ptype": "成品馅", "team": "拌馅组", "cooled": False, "packed": True, "sort": 3,
                                       "note": "示例产品"}, name="葱油鲜肉馅（示例）")
    for p, lines in [(oil, [("大豆油", None, "100"), ("大葱", None, "30")]),
                     (demo, [("冻 2 号", None, "500"), ("葱", None, "60"), (None, "葱油（示例）", "40"),
                             (None, "麻油", "10"), ("蛋白鲜肉馅干调", None, "30"), ("水", None, "100")])]:
        if db.scalars(select(Bom).where(Bom.product_id == p.id)).first() is None:
            b = Bom(product_id=p.id, effective_date=BASE_DATE, note="示例")
            for i, (mname, pname, qty) in enumerate(lines, start=1):
                b.lines.append(BomLine(line_no=i, material_id=mats[mname].id if mname else None,
                                       input_product_id=prods.get(pname, oil).id if pname else None, qty=D(qty)))
            db.add(b)
    prods = {p.name: p for p in db.scalars(select(Product))}
    prods["麻油"].fallback_price = prods["麻油"].fallback_price or D("21.00")
    for name, (cook, cool, pack) in {"粉丝馅料": ("0.92", "0.985", "0.995"), "蛋白鲜肉馅料": ("0.995", None, "0.996"),
                                     "葱油（示例）": ("0.85", "0.99", None), "葱油鲜肉馅（示例）": ("0.99", None, "0.996"),
                                     "麻油": ("0.45", None, None)}.items():
        get_or_create(db, ProductStdYield, {"cook_yield": D(cook), "cool_yield": D(cool) if cool else None,
                                            "pack_yield": D(pack) if pack else None},
                      product_id=prods[name].id, effective_date=BASE_DATE)

    start = date(2026, 10, 12)
    meters = list(db.scalars(select(Meter).order_by(Meter.id)))
    for k in range(3):
        d = start + timedelta(days=k)
        if db.scalars(select(DailyProduction).where(DailyProduction.date == d)).first():
            continue
        bump = D(k) / 100  # 每天价格、称重略有变化
        for name, price in DEMO_PRICE.items():
            db.add(MaterialPrice(material_id=mats[name].id, date=d, price=D(price) * (1 + bump), source="示例"))
        for name, q1, q2 in [("肥膘", "600", "571"), ("大蒜", "40", "33.5"), ("大葱", "80", "63"), ("葱", "160", "130"),
                             ("姜", "120", "101"), ("老豆腐丁", "320", "314"), ("红薯粉条", "160", "418"),
                             ("冻 2 号", "1300", "1262")]:
            q2v = D(q2) * (1 - bump)
            db.add(DailyMaterialProcess(date=d, material_id=mats[name].id, qty1=D(q1), qty2=q2v))
        # 制馅
        db.add(DailyProduction(date=d, product_id=prods["粉丝馅料"].id, batches=D(4), output_weight=D("1196.5") - k * 8))
        db.add(DailyProduction(date=d, product_id=prods["蛋白鲜肉馅料"].id, batches=D(1), output_weight=D("1884.6")))
        db.add(DailyProduction(date=d, product_id=prods["葱油（示例）"].id, batches=D(2), output_weight=D("221")))
        db.add(DailyProduction(date=d, product_id=prods["葱油鲜肉馅（示例）"].id, batches=D(1), output_weight=D("733")))
        db.add(DailyProduction(date=d, product_id=prods["麻油"].id, qty_in=D("500"), output_weight=D("226") - k * 3))
        # 制冷
        db.add(DailyCooling(date=d, product_id=prods["粉丝馅料"].id, cooled_weight=D("1176") - k * 9))
        db.add(DailyCooling(date=d, product_id=prods["葱油（示例）"].id, cooled_weight=D("219")))
        # 包装
        for pname, packed, bags in [("粉丝馅料", D("1170") - k * 9, {"5斤袋": 150, "20斤袋": 21}),
                                    ("蛋白鲜肉馅料", D("1876"), {"20斤袋": 93, "2斤袋": 8}),
                                    ("葱油鲜肉馅（示例）", D("730"), {"15斤袋": 48, "5斤袋": 2})]:
            pk = DailyPacking(date=d, product_id=prods[pname].id, packed_weight=packed)
            for sname, n in bags.items():
                pk.bags.append(DailyPackingBag(spec_id=specs[sname].id, bags=D(n)))
            db.add(pk)
    # 抄表：起始日前一天先填一次底数
    base = {m.id: D(1000 + 37 * m.id) for m in meters}
    # 每块表每天的示例读数差
    use = {"大锅区域": 22, "小锅区域": 14, "豆沙区域": 9, "食堂区域": 5, "锅炉房 1#": 30, "锅炉房 2#": 26, "研发室": 1,
           "储福记": 75, "和善园": 15, "工厂井水": 20, "储#1": 1, "物流洗车区": 2, "水站总表": 3, "洗筐区总表": 4,
           "生加工（单独）": 2, "洗筐间（单独）": 1.5, "锅炉房": 3, "和善园 #1": 0.42, "储#2": 6, "榨油车间": 2,
           "OEM 库 1": 0.8, "OEM 库 2": 0.6, "原料库": 1.1}
    for k in range(4):
        d = start + timedelta(days=k - 1)
        for m in meters:
            if db.scalars(select(MeterReading).where(MeterReading.date == d, MeterReading.meter_id == m.id)).first():
                continue
            if m.name.startswith("光伏"):
                val = D(320 + 10 * k)
            elif m.energy == "elec" and m.name == "储#1":
                val = base[m.id] + D("0.05") * k
            else:
                val = base[m.id] + D(str(use.get(m.name, 1))) * k
            db.add(MeterReading(date=d, meter_id=m.id, reading=val))
    db.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    if args.reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    init_base(db)
    if args.demo:
        init_demo(db)
    db.commit()
    print(recalc_from(db, None))
    db.close()


if __name__ == "__main__":
    main()
