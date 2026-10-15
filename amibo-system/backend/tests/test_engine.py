"""计算引擎测试：用手算结果核对公式。"""
from datetime import date, timedelta
from decimal import Decimal as D

from sqlalchemy import select

from app.calc.engine import recalc_from
from app.models import (
    Bom, BomLine, CalcEnergy, CalcIssue, CalcMaterial, CalcProduct, DailyCooling, DailyMaterialProcess, DailyPacking,
    DailyPackingBag, DailyProduction, EnergyPrice, Material, MaterialPrice, MaterialStdYield, Meter, MeterReading,
    MeterVersion, PackSpec, PackSpecVersion, Product, ProductStdYield, SeasoningPrice,
)

D0 = date(2026, 1, 1)
DAY = date(2026, 3, 2)


def close(a, b, tol=D("1e-20")):
    assert a is not None and b is not None, (a, b)
    assert abs(D(a) - D(b)) < tol, (a, b)


def mat(db, name, cat, proc=False, std=None):
    m = Material(name=name, category=cat, needs_process=proc)
    db.add(m)
    db.flush()
    if std is not None:
        db.add(MaterialStdYield(material_id=m.id, effective_date=D0, std_yield=D(std)))
    return m


def product(db, name, ptype="成品馅", cooled=False, packed=True, cook=None, cool=None, pack=None, **kw):
    p = Product(name=name, ptype=ptype, cooled=cooled, packed=packed, **kw)
    db.add(p)
    db.flush()
    if any(x is not None for x in (cook, cool, pack)):
        db.add(ProductStdYield(product_id=p.id, effective_date=D0, cook_yield=D(cook) if cook else None,
                               cool_yield=D(cool) if cool else None, pack_yield=D(pack) if pack else None))
    return p


def bom(db, p, lines):
    b = Bom(product_id=p.id, effective_date=D0)
    for i, (ref, qty) in enumerate(lines, start=1):
        if isinstance(ref, Product):
            b.lines.append(BomLine(line_no=i, input_product_id=ref.id, qty=D(qty)))
        else:
            b.lines.append(BomLine(line_no=i, material_id=ref.id, qty=D(qty)))
    db.add(b)
    db.flush()
    return b


def spec(db, name, w, fee):
    s = PackSpec(name=name)
    db.add(s)
    db.flush()
    db.add(PackSpecVersion(spec_id=s.id, effective_date=D0, bag_weight=D(w), fee=D(fee)))
    return s


def calc(db, pid, day=DAY):
    return db.scalars(select(CalcProduct).where(CalcProduct.product_id == pid, CalcProduct.date == day)).one()


def build_chain(db):
    ginger = mat(db, "姜", "蔬菜", True, "0.85")
    oil = mat(db, "油", "调料")
    sx = mat(db, "干调X", "干调")
    water = mat(db, "水", "水")
    db.add(SeasoningPrice(material_id=sx.id, effective_date=D0, price=D(6)))
    p = product(db, "测试馅", cooled=True, cook="0.9", cool="0.98", pack="0.99")
    bom(db, p, [(ginger, 10), (oil, 20), (oil, 5), (sx, 4), (water, 11)])
    s5, s2 = spec(db, "5斤", 5, "0.5"), spec(db, "2斤", 2, "0.3")
    db.add(MaterialPrice(material_id=ginger.id, date=DAY, price=D(4)))
    db.add(MaterialPrice(material_id=oil.id, date=DAY, price=D(5)))
    db.add(DailyMaterialProcess(date=DAY, material_id=ginger.id, qty1=D(100), qty2=D(80)))
    db.add(DailyProduction(date=DAY, product_id=p.id, batches=D(2), output_weight=D(92)))
    db.add(DailyCooling(date=DAY, product_id=p.id, cooled_weight=D(90)))
    pk = DailyPacking(date=DAY, product_id=p.id, packed_weight=D(89))
    pk.bags.append(DailyPackingBag(spec_id=s5.id, bags=D(17)))
    pk.bags.append(DailyPackingBag(spec_id=s2.id, bags=D(2)))
    db.add(pk)
    db.commit()
    return p, ginger


def test_cost_chain_matches_hand_calculation(db):
    p, ginger = build_chain(db)
    recalc_from(db)
    m = db.scalars(select(CalcMaterial).where(CalcMaterial.material_id == ginger.id)).one()
    close(m.actual_yield, D("0.8"))
    close(m.price2_actual, D(5))
    close(m.price2_std, D(4) / D("0.85"))

    c = calc(db, p.id)
    assert c.ok
    close(c.input_weight, D(100))
    close(c.input_cost_actual, D(398))  # 2 × (10×5 + 25×5 + 4×6 + 11×0)
    close(c.cook_yield_actual, D("0.92"))
    close(c.out_price_actual, D(398) / D(92))
    close(c.cooled_price_actual, D(398) / D(90))
    close(c.bag_fee, D("9.1"))
    close(c.final_price_actual, (D(398) + D("9.1")) / D(89))

    unit_s = (D(10) * D(4) / D("0.85") + D(125) + D(24)) / D(50)
    out_s = unit_s / D("0.9")
    final_s = out_s / D("0.98") / D("0.99") + D("9.1") / D(89)
    close(c.out_price_std, out_s)
    close(c.final_price_std, final_s)
    close(c.diff_price, c.final_price_actual - final_s)
    close(c.diff_amount, (c.final_price_actual - final_s) * D(89))

    # 归因各项之和 = 总差额
    total = sum(D(a["per_jin"]) for a in c.attribution)
    close(total, c.diff_price)
    assert {a["key"] for a in c.attribution} == {f"m:{ginger.id}", "cook", "cool", "pack"}

    # 溯源：BOM 原行保留（油两行）
    names = [l["name"] for l in c.trace["lines"]]
    assert names.count("油") == 2


def test_single_spec_equivalent_formula(db):
    """只有一种规格时：成品单价 = 包装前单价 ÷ 包装出率 + 袋费 ÷ 每袋斤数。"""
    oil = mat(db, "油", "调料")
    p = product(db, "单规格", cook="1", pack="1")
    bom(db, p, [(oil, 100)])
    s = spec(db, "20斤", 20, "1.5")
    db.add(MaterialPrice(material_id=oil.id, date=DAY, price=D(5)))
    db.add(DailyProduction(date=DAY, product_id=p.id, batches=D(1), output_weight=D(100)))
    pk = DailyPacking(date=DAY, product_id=p.id, packed_weight=D(100))
    pk.bags.append(DailyPackingBag(spec_id=s.id, bags=D(5)))
    db.add(pk)
    db.commit()
    recalc_from(db)
    c = calc(db, p.id)
    close(c.final_price_actual, D(5) / D(1) + D("1.5") / D(20))


def test_material_without_record_uses_std_and_no_price_blocks_cost(db):
    ginger = mat(db, "姜", "蔬菜", True, "0.85")
    garlic = mat(db, "蒜", "蔬菜", True, "0.8")
    p = product(db, "馅A", packed=False, cook="1")
    bom(db, p, [(ginger, 10), (garlic, 10)])
    db.add(MaterialPrice(material_id=ginger.id, date=DAY, price=D(4)))
    db.add(DailyProduction(date=DAY, product_id=p.id, batches=D(1), output_weight=D(20)))
    db.commit()
    recalc_from(db)
    m = db.scalars(select(CalcMaterial).where(CalcMaterial.material_id == ginger.id)).one()
    assert m.yield_source == "std"
    close(m.actual_yield, D("0.85"))
    c = calc(db, p.id)
    assert not c.ok and c.out_price_actual is None
    msgs = [i.message for i in db.scalars(select(CalcIssue).where(CalcIssue.kind == "warning"))]
    assert any("缺单价" in x and "蒜" in x for x in msgs)
    # 不自动取旧价：前一天有价也不用
    db.add(MaterialPrice(material_id=garlic.id, date=DAY - timedelta(days=1), price=D(3)))
    db.commit()
    recalc_from(db)
    assert not calc(db, p.id).ok


def test_yield_over_100_percent_is_not_error_and_alert_threshold(db):
    noodle = mat(db, "粉条", "泡发", True, "2.6")
    p = product(db, "馅B", packed=False, cook="1")
    bom(db, p, [(noodle, 10)])
    db.add(MaterialPrice(material_id=noodle.id, date=DAY, price=D(5)))
    db.add(DailyMaterialProcess(date=DAY, material_id=noodle.id, qty1=D(100), qty2=D(258)))  # 258%，偏差 -2pp
    db.add(DailyProduction(date=DAY, product_id=p.id, batches=D(1), output_weight=D(10)))
    db.commit()
    recalc_from(db)
    assert not db.scalars(select(CalcIssue).where(CalcIssue.kind == "alert")).all()
    db.execute(DailyMaterialProcess.__table__.update().values(qty2=D(250)))  # -10pp
    db.commit()
    recalc_from(db)
    alerts = db.scalars(select(CalcIssue).where(CalcIssue.kind == "alert")).all()
    assert len(alerts) == 1 and alerts[0].object_name == "粉条"
    close(alerts[0].dev_pp, D(-10))


def test_semi_oil_previous_day_and_recalc_propagation(db):
    oil = mat(db, "油", "调料")
    water = mat(db, "水", "水")
    s = product(db, "葱油", ptype="半成品油", cooled=True, packed=False, cook="0.9", cool="1")
    q = product(db, "用油馅", packed=False, cook="1")
    bom(db, s, [(oil, 10)])
    bom(db, q, [(s, 10), (water, 10)])
    d1, d2 = DAY, DAY + timedelta(days=1)
    for d in (d1, d2):
        db.add(MaterialPrice(material_id=oil.id, date=d, price=D(5)))
    db.add(DailyProduction(date=d1, product_id=s.id, batches=D(1), output_weight=D(9)))
    db.add(DailyCooling(date=d1, product_id=s.id, cooled_weight=D(9)))
    db.add(DailyProduction(date=d2, product_id=q.id, batches=D(1), output_weight=D(20)))
    db.commit()
    recalc_from(db)
    c = calc(db, q.id, d2)
    close(c.input_cost_actual, D(10) * D(50) / D(9))
    assert c.trace["lines"][0]["date"] == d1.isoformat()

    # 改前一天半成品油的冷后重量，次日跟着变
    db.execute(DailyCooling.__table__.update().values(cooled_weight=D(8)))
    db.commit()
    recalc_from(db, d1)
    close(calc(db, q.id, d2).input_cost_actual, D(10) * D(50) / D(8))


def test_semi_oil_fallback_price(db):
    water = mat(db, "水", "水")
    s = product(db, "红油", ptype="半成品油", cooled=True, packed=False, fallback_price=D("7.5"))
    q = product(db, "馅C", packed=False, cook="1")
    bom(db, q, [(s, 10), (water, 10)])
    db.add(DailyProduction(date=DAY, product_id=q.id, batches=D(1), output_weight=D(20)))
    db.commit()
    recalc_from(db)
    close(calc(db, q.id).input_cost_actual, D(75))


def test_sesame_oil_weighted_previous_7_days(db):
    sesame = mat(db, "芝麻", "芝麻")
    water = mat(db, "水", "水")
    so = product(db, "麻油", ptype="麻油", packed=False, cook="0.45", source_material_id=sesame.id)
    r = product(db, "麻油馅", packed=False, cook="1")
    bom(db, r, [(so, 10), (water, 10)])
    d1, d2, d3 = DAY, DAY + timedelta(days=1), DAY + timedelta(days=2)
    for d in (d1, d2):
        db.add(MaterialPrice(material_id=sesame.id, date=d, price=D(9)))
    db.add(DailyProduction(date=d1, product_id=so.id, qty_in=D(100), output_weight=D(45)))
    db.add(DailyProduction(date=d2, product_id=so.id, qty_in=D(100), output_weight=D(40)))
    db.add(DailyProduction(date=d3, product_id=r.id, batches=D(1), output_weight=D(20)))
    db.commit()
    recalc_from(db)
    close(calc(db, so.id, d1).out_price_actual, D(20))
    close(calc(db, so.id, d2).out_price_actual, D("22.5"))
    expected = (D(20) * 45 + D("22.5") * 40) / 85
    close(calc(db, r.id, d3).input_cost_actual, expected * 10)
    # 总产量包含麻油
    close(db.get(CalcEnergy, d1).total_output, D(45))


def test_energy_totals(db):
    def meter(name, energy, factor="1", plant="+", ws="", mode="reading"):
        m = Meter(name=name, energy=energy)
        db.add(m)
        db.flush()
        db.add(MeterVersion(meter_id=m.id, effective_date=D0, mode=mode, factor=D(factor), plant=plant, workshop=ws))
        return m

    a = meter("大锅", "gas")
    b = meter("储福记", "gas", "0.08", "-")
    w1 = meter("井水", "water", "1", "+", "+")
    w2 = meter("和善园", "water", "1", "+", "")
    w3 = meter("生加工", "water", "1", "ref", "ref")
    e1 = meter("和善园#1", "elec", "2000")
    pv = meter("光伏", "elec", "1", "+", "", "direct")
    for k, v in {"gas": "4.3741", "water": "4.49", "elec": "0.8644"}.items():
        db.add(EnergyPrice(energy=k, effective_date=D0, price=D(v)))
    d0, d1 = DAY - timedelta(days=1), DAY
    vals = {a: (100, 300), b: (1000, 2000), w1: (10, 40), w2: (5, 15), w3: (1, 9), e1: ("10.5", "11.25"), pv: (0, 120)}
    for m, (x0, x1) in vals.items():
        db.add(MeterReading(date=d0, meter_id=m.id, reading=D(str(x0))))
        db.add(MeterReading(date=d1, meter_id=m.id, reading=D(str(x1))))
    # 当日产量 4000 斤 = 2 吨
    oil = mat(db, "油", "调料")
    p = product(db, "馅", packed=True, cook="1", pack="1")
    bom(db, p, [(oil, 100)])
    db.add(DailyProduction(date=d1, product_id=p.id, batches=D(40), output_weight=D(4000)))
    db.add(DailyPacking(date=d1, product_id=p.id, packed_weight=D(4000)))
    db.commit()
    recalc_from(db)
    e = db.get(CalcEnergy, d1)
    sm = e.data["summary"]
    close(sm["gas"]["plant"], D(200) - D(1000) * D("0.08"))  # 120
    close(sm["water"]["plant"], D(30 + 10))
    close(sm["water"]["workshop"], D(30))
    close(sm["elec"]["plant"], D("0.75") * 2000 + 120)  # 1620
    close(sm["gas"]["per_ton"], D(60))
    close(sm["water"]["outside_per_ton"], D(5))
    close(sm["elec"]["cost"], D(1620) * D("0.8644"))

    # 换表 + 读数变小提示
    d2 = DAY + timedelta(days=1)
    db.add(MeterReading(date=d2, meter_id=a.id, reading=D(50), old_final=D(320), new_start=D(0)))
    db.add(MeterReading(date=d2, meter_id=w2.id, reading=D(3)))
    db.commit()
    recalc_from(db)
    rows = {r["name"]: r for r in db.get(CalcEnergy, d2).data["meters"]}
    close(rows["大锅"]["usage"], D(20 + 50))
    assert rows["和善园"]["usage"] is None
    assert any("小于上期" in i.message for i in db.scalars(select(CalcIssue).where(CalcIssue.date == d2)))


def test_demo_attribution_sums(demo):
    for c in demo.scalars(select(CalcProduct).where(CalcProduct.ok.is_(True))):
        if c.attribution and c.diff_price is not None:
            close(sum(D(a["per_jin"]) for a in c.attribution), c.diff_price, D("1e-18"))
