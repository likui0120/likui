"""计算引擎：按天算出率、实际成本、标准成本、差额归因和异常。

计算顺序（单价单位 元/斤，重量单位 斤）：
1. 原料 1→2 级出率 = 2 级称重 ÷ 1 级领用量；无处理记录用标准出率；不需处理的固定 100%。
   2 级单价 = 1 级单价 ÷ 出率。
2. 产品投料成本 = 锅数 × Σ(BOM 每行数量 × 该行单价)。
   出机单价 = 投料成本 ÷ 出锅重（出机重）。
3. 冷后单价 = 出机单价 ÷ 制冷出率（仅经过制冷的产品）。
4. 成品单价 = (包装前单价 × 包装前重量 + Σ 袋数 × 袋费) ÷ 包装入库量。
5. 麻油单价 = 芝麻 1 级单价 ÷ 麻油出率。
标准成本用同一套公式，把每个实际出率换成标准出率，单价不变。
半成品油取之前最近一天的冷后单价，麻油取前 7 天（或上一自然周）按产量加权的单价，
所以同一天内产品之间没有依赖，只依赖更早的日期。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import (
    AlertThreshold, Bom, CalcEnergy, CalcIssue, CalcMaterial, CalcProduct, DailyCooling,
    DailyMaterialProcess, DailyPacking, DailyProduction, Material, MaterialPrice,
    MaterialStdYield, PackSpecVersion, Product, ProductStdYield, SeasoningPrice, STAGES,
)
from ..settings import get_setting
from .energy import calc_energy_day
from .versions import effective_rows

ONE = Decimal(1)
ZERO = Decimal(0)
HUNDRED = Decimal(100)


def js(v):
    """Decimal 转成 JSON 可存的字符串。"""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return str(v)
    return v


def div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


# ---------------------------------------------------------------- 阈值

class Thresholds:
    def __init__(self, db: Session):
        self.glob = Decimal(get_setting(db, "global_threshold"))
        self.cat, self.mat, self.stage, self.pstage = {}, {}, {}, {}
        for r in db.scalars(select(AlertThreshold)):
            if r.scope == "global":
                self.glob = r.value
            elif r.scope == "category":
                self.cat[r.category] = r.value
            elif r.scope == "material":
                self.mat[r.material_id] = r.value
            elif r.scope == "stage":
                self.stage[r.stage] = r.value
            elif r.scope == "product_stage":
                self.pstage[(r.product_id, r.stage)] = r.value

    def for_material(self, m: Material) -> Decimal:
        return self.mat.get(m.id) or self.cat.get(m.category) or self.glob

    def for_product(self, pid: int, stage: str) -> Decimal:
        return self.pstage.get((pid, stage)) or self.stage.get(stage) or self.glob


# ---------------------------------------------------------------- 原料结果

@dataclass
class MatRes:
    m: Material
    qty1: Decimal | None = None
    qty2: Decimal | None = None
    actual: Decimal | None = None
    std: Decimal | None = None
    source: str = "fixed"  # actual / std / fixed / missing
    std_missing: bool = False
    price1: Decimal | None = None
    p2a: Decimal | None = None
    p2s: Decimal | None = None
    used: bool = False


@dataclass
class Line:
    """一行 BOM 投料，带实际/标准单价，用于计算与归因。"""

    line_no: int
    name: str
    kind: str  # 原料 / 原料(不处理) / 干调 / 水 / 半成品油 / 麻油
    qty: Decimal
    pa: Decimal | None
    ps: Decimal | None
    key: str | None = None  # 归因因素
    info: dict = field(default_factory=dict)


class DayCalc:
    def __init__(self, db: Session, day: date):
        self.db = db
        self.day = day
        self.issues: list[CalcIssue] = []
        self.th = Thresholds(db)
        self.suspect = Decimal(get_setting(db, "suspect_pp"))
        self.sesame_rule = get_setting(db, "sesame_rule")

        self.materials = {m.id: m for m in db.scalars(select(Material))}
        self.products = {p.id: p for p in db.scalars(select(Product))}
        self.mat_std = {k: v.std_yield for k, v in effective_rows(db, MaterialStdYield, "material_id", day).items()}
        self.prod_std = effective_rows(db, ProductStdYield, "product_id", day)
        self.season = {k: v.price for k, v in effective_rows(db, SeasoningPrice, "material_id", day).items()}
        self.specs = effective_rows(db, PackSpecVersion, "spec_id", day)
        self.boms = effective_rows(db, Bom, "product_id", day)
        self.prices = {
            r.material_id: r.price
            for r in db.scalars(select(MaterialPrice).where(MaterialPrice.date == day))
        }
        self.process = {
            r.material_id: r
            for r in db.scalars(select(DailyMaterialProcess).where(DailyMaterialProcess.date == day))
        }
        self.production = list(db.scalars(select(DailyProduction).where(DailyProduction.date == day)))
        self.cooling = {
            r.product_id: r for r in db.scalars(select(DailyCooling).where(DailyCooling.date == day))
        }
        self.packing = {
            r.product_id: r for r in db.scalars(select(DailyPacking).where(DailyPacking.date == day))
        }
        self.mat_res: dict[int, MatRes] = {}

    # ------------------------------------------------------------ 工具

    def issue(self, kind, key, name, message, stage=None, actual=None, std=None, dev=None, threshold=None):
        self.issues.append(CalcIssue(
            date=self.day, kind=kind, item_key=key, object_name=name, stage=stage,
            actual=actual, std=std, dev_pp=dev, threshold=threshold, message=message,
        ))

    def check_yield(self, key, name, stage, actual, std, threshold):
        """实际与标准对比，超阈值进异常清单。"""
        if actual is None or std is None:
            return
        dev = (actual - std) * HUNDRED
        if abs(dev) > threshold:
            msg = f"{STAGES.get(stage, stage)}出率 {actual * HUNDRED:.2f}% ，标准 {std * HUNDRED:.2f}% ，偏差 {dev:+.2f} 个百分点"
            if abs(dev) > self.suspect:
                msg += "（偏差极大，请核对是否录错）"
            self.issue("alert", key, name, msg, stage, actual, std, dev, threshold)

    # ------------------------------------------------------------ 原料

    def material(self, mid: int) -> MatRes:
        if mid in self.mat_res:
            return self.mat_res[mid]
        m = self.materials[mid]
        r = MatRes(m=m, price1=self.prices.get(mid))
        rec = self.process.get(mid)
        if rec is not None:
            r.qty1, r.qty2 = rec.qty1, rec.qty2
        if not m.needs_process:
            r.actual = r.std = ONE
            r.source = "fixed"
        else:
            r.std = self.mat_std.get(mid)
            if rec is not None and rec.qty1:
                r.actual = rec.qty2 / rec.qty1
                r.source = "actual"
                if r.std is None:
                    r.std = r.actual
                    r.std_missing = True
            elif r.std is not None:
                r.actual = r.std
                r.source = "std"
            else:
                r.source = "missing"
        if r.price1 is not None:
            r.p2a = div(r.price1, r.actual)
            r.p2s = div(r.price1, r.std)
        self.mat_res[mid] = r
        return r

    # ------------------------------------------------------------ 上游产品单价

    def upstream_price(self, p: Product):
        """半成品油：之前最近一天的实际冷后单价；麻油：前 7 天（或上一自然周）按产量加权。

        返回 (实际单价, 标准单价, 说明 dict)；取不到返回 None。
        """
        db = self.db
        base = select(CalcProduct).where(
            CalcProduct.product_id == p.id, CalcProduct.ok.is_(True), CalcProduct.date < self.day
        )

        def price_of(row, std=False):
            if std:
                return row.cooled_price_std if row.cooled_price_std is not None else row.out_price_std
            return row.cooled_price_actual if row.cooled_price_actual is not None else row.out_price_actual

        if p.ptype == "麻油":
            if self.sesame_rule == "prev_week":
                monday = self.day - timedelta(days=self.day.weekday())
                start, end = monday - timedelta(days=7), monday - timedelta(days=1)
                rule = "上一自然周按产量加权"
            else:
                start, end = self.day - timedelta(days=7), self.day - timedelta(days=1)
                rule = "前7天按产量加权"
            rows = [r for r in db.scalars(base.where(CalcProduct.date >= start, CalcProduct.date <= end))
                    if r.output_weight and price_of(r) is not None]
            if rows:
                w = sum(r.output_weight for r in rows)
                pa = sum(price_of(r) * r.output_weight for r in rows) / w
                ps = sum((price_of(r, True) or price_of(r)) * r.output_weight for r in rows) / w
                return pa, ps, {"rule": rule, "from": start.isoformat(), "to": end.isoformat(),
                                "days": [r.date.isoformat() for r in rows]}
        row = db.scalars(base.order_by(CalcProduct.date.desc()).limit(1)).first()
        if row is not None and price_of(row) is not None:
            return price_of(row), (price_of(row, True) or price_of(row)), {
                "rule": "最近一次实际单价", "date": row.date.isoformat()}
        if p.fallback_price is not None:
            return p.fallback_price, p.fallback_price, {"rule": "无历史单价，用标准单价"}
        return None

    # ------------------------------------------------------------ 产品

    def calc_sesame_oil(self, rec: DailyProduction, p: Product) -> CalcProduct:
        std_row = self.prod_std.get(p.id)
        std = std_row.cook_yield if std_row else None
        actual = div(rec.output_weight, rec.qty_in)
        sesame = self.materials.get(p.source_material_id) if p.source_material_id else None
        price1 = self.prices.get(sesame.id) if sesame else None
        if sesame:
            self.material(sesame.id).used = True
        key = f"p:{p.id}:oil"
        if std is None and actual is not None:
            std = actual
            self.issue("warning", key, p.name, "缺麻油标准出率，标准成本按实际出率计", "oil")
        cp = CalcProduct(date=self.day, product_id=p.id, input_weight=rec.qty_in, output_weight=rec.output_weight,
                         cook_yield_actual=actual, cook_yield_std=std)
        if sesame is None:
            self.issue("warning", key, p.name, "产品资料未指定芝麻原料，无法计算麻油单价", "oil")
        elif price1 is None:
            self.issue("warning", f"m:{sesame.id}:price", sesame.name, "缺芝麻 1 级单价，麻油不出成本")
        cp.ok = price1 is not None and actual is not None
        if cp.ok:
            cp.input_cost_actual = cp.input_cost_std = price1 * rec.qty_in
            cp.out_price_actual = price1 / actual
            cp.out_price_std = div(price1, std)
            cp.diff_price = cp.out_price_actual - cp.out_price_std if cp.out_price_std is not None else None
            cp.diff_amount = cp.diff_price * rec.output_weight if cp.diff_price is not None else None
        cp.trace = {"kind": "麻油", "sesame": sesame.name if sesame else None, "sesame_qty": js(rec.qty_in),
                    "price1": js(price1), "yield_actual": js(actual), "yield_std": js(std)}
        if cp.ok and cp.diff_price:
            cp.attribution = [{"factor": "麻油出率", "per_jin": js(cp.diff_price), "amount": js(cp.diff_amount)}]
        self.check_yield(key, p.name, "oil", actual, std, self.th.for_product(p.id, "oil"))
        return cp

    def calc_product(self, rec: DailyProduction, p: Product) -> CalcProduct:
        if p.ptype == "麻油":
            return self.calc_sesame_oil(rec, p)
        cp = CalcProduct(date=self.day, product_id=p.id, output_weight=rec.output_weight, ok=False)
        bom = self.boms.get(p.id)
        std_row = self.prod_std.get(p.id)
        if bom is None or not bom.lines:
            self.issue("warning", f"p:{p.id}:bom", p.name, "当天没有有效的 BOM，无法计算")
            return cp
        batches = rec.batches or ZERO
        if batches <= 0:
            self.issue("warning", f"p:{p.id}:cook", p.name, "锅数/机数为空或为 0，无法计算")
            return cp

        # ---- BOM 行单价
        lines: list[Line] = []
        missing: list[str] = []
        for bl in bom.lines:
            if bl.input_product_id:
                up = self.products[bl.input_product_id]
                res = self.upstream_price(up)
                if res is None:
                    missing.append(f"{up.name}（无历史单价，也未设标准单价）")
                    lines.append(Line(bl.line_no, up.name, up.ptype, bl.qty, None, None))
                    continue
                pa, ps, info = res
                lines.append(Line(bl.line_no, up.name, up.ptype, bl.qty, pa, ps,
                                  key=f"u:{up.id}" if pa != ps else None, info=info))
                continue
            m = self.materials[bl.material_id]
            if m.category == "水":
                lines.append(Line(bl.line_no, m.name, "水", bl.qty, ZERO, ZERO))
            elif m.category == "干调":
                sp = self.season.get(m.id)
                if sp is None:
                    missing.append(f"{m.name}（干调价格）")
                lines.append(Line(bl.line_no, m.name, "干调", bl.qty, sp, sp))
            else:
                r = self.material(m.id)
                r.used = True
                if r.price1 is None:
                    missing.append(f"{m.name}（1 级单价）")
                elif r.p2a is None:
                    missing.append(f"{m.name}（无处理记录也无标准出率）")
                kind = "原料" if m.needs_process else "原料(不处理)"
                key = f"m:{m.id}" if m.needs_process and r.source == "actual" and r.actual != r.std else None
                lines.append(Line(bl.line_no, m.name, kind, bl.qty, r.p2a, r.p2s, key=key, info={
                    "price1": js(r.price1), "yield_actual": js(r.actual), "yield_std": js(r.std),
                    "yield_source": r.source,
                }))

        per_batch = sum(l.qty for l in lines)
        input_weight = batches * per_batch
        cp.input_weight = input_weight

        # ---- 熟制 / 拌馅出率
        cook_a = div(rec.output_weight, input_weight)
        cook_s = std_row.cook_yield if std_row and std_row.cook_yield is not None else None
        if cook_s is None and cook_a is not None:
            cook_s = cook_a
            self.issue("warning", f"p:{p.id}:cook", p.name, "缺熟制/拌馅标准出率，标准成本按实际出率计", "cook")
        cp.cook_yield_actual, cp.cook_yield_std = cook_a, cook_s
        self.check_yield(f"p:{p.id}:cook", p.name, "cook", cook_a, cook_s, self.th.for_product(p.id, "cook"))

        # ---- 制冷
        cool_a = cool_s = None
        if p.cooled:
            cool_s = std_row.cool_yield if std_row and std_row.cool_yield is not None else None
            crec = self.cooling.get(p.id)
            if crec is not None:
                cp.cooled_weight = crec.cooled_weight
                cool_a = div(crec.cooled_weight, rec.output_weight)
                cp.cool_source = "actual"
                if cool_s is None:
                    cool_s = cool_a
                    self.issue("warning", f"p:{p.id}:cool", p.name, "缺制冷标准出率，标准成本按实际出率计", "cool")
                self.check_yield(f"p:{p.id}:cool", p.name, "cool", cool_a, cool_s, self.th.for_product(p.id, "cool"))
            elif cool_s is not None:
                cool_a = cool_s
                cp.cool_source = "std"
                cp.cooled_weight = rec.output_weight * cool_s
                self.issue("warning", f"p:{p.id}:cool", p.name, "缺制冷记录，按标准制冷出率估算", "cool")
            else:
                cp.cool_source = "missing"
                self.issue("warning", f"p:{p.id}:cool", p.name, "缺制冷记录，也没有标准制冷出率", "cool")
            cp.cool_yield_actual, cp.cool_yield_std = cool_a, cool_s

        # ---- 包装
        pack_a = pack_s = None
        bag_fee_total = ZERO
        bag_detail = []
        packed = p.packed and p.ptype == "成品馅"
        prec = self.packing.get(p.id)
        if packed:
            pack_s = std_row.pack_yield if std_row and std_row.pack_yield is not None else None
            if prec is None:
                self.issue("warning", f"p:{p.id}:pack", p.name, "缺包装记录，不出成品单价", "pack")
            else:
                default_pre = cp.cooled_weight if p.cooled else rec.output_weight
                cp.prepack_weight = prec.prepack_weight if prec.prepack_weight is not None else default_pre
                cp.packed_weight = prec.packed_weight
                pack_a = div(prec.packed_weight, cp.prepack_weight)
                if pack_s is None and pack_a is not None:
                    pack_s = pack_a
                    self.issue("warning", f"p:{p.id}:pack", p.name, "缺包装标准出率，标准成本按实际出率计", "pack")
                self.check_yield(f"p:{p.id}:pack", p.name, "pack", pack_a, pack_s, self.th.for_product(p.id, "pack"))
                bag_weight_sum = ZERO
                for b in prec.bags:
                    sv = self.specs.get(b.spec_id)
                    if sv is None:
                        missing.append("包装规格袋费")
                        continue
                    bag_fee_total += b.bags * sv.fee
                    bag_weight_sum += b.bags * sv.bag_weight
                    bag_detail.append({"spec_id": b.spec_id, "bags": js(b.bags), "fee": js(sv.fee),
                                       "bag_weight": js(sv.bag_weight), "amount": js(b.bags * sv.fee)})
                if bag_weight_sum and prec.packed_weight:
                    gap = abs(bag_weight_sum - prec.packed_weight) / prec.packed_weight
                    if gap > Decimal("0.05"):
                        self.issue("warning", f"p:{p.id}:bags", p.name,
                                   f"袋数 × 每袋斤数 = {bag_weight_sum:.2f} 斤，与包装入库量 {prec.packed_weight:.2f} 斤相差较大，请核对", "pack")
            cp.pack_yield_actual, cp.pack_yield_std = pack_a, pack_s
            cp.bag_fee = bag_fee_total if prec is not None else None

        # ---- 单价（实际 / 标准）
        bag_per_jin = div(bag_fee_total, cp.packed_weight) if cp.packed_weight else ZERO

        def evaluate(switched: set[str]):
            """按给定的“已换成标准”的因素集合算出各环节单价。全空 = 实际，全换 = 标准。"""
            tot = ZERO
            for l in lines:
                pr = l.ps if (l.key in switched or "all" in switched) else l.pa
                tot += l.qty * pr
            unit_in = tot / per_batch
            std_all = "all" in switched
            cy = cook_s if (std_all or "cook" in switched) else cook_a
            out = div(unit_in, cy)
            cooled = None
            if p.cooled:
                vy = cool_s if (std_all or "cool" in switched) else cool_a
                cooled = div(out, vy)
            final = None
            if packed and prec is not None:
                py = pack_s if (std_all or "pack" in switched) else pack_a
                pre = cooled if p.cooled else out
                final = div(pre, py)
                if final is not None:
                    final += bag_per_jin
            return out, cooled, final

        if missing:
            self.issue("warning", f"p:{p.id}:price", p.name, "缺单价，不出成本：" + "、".join(dict.fromkeys(missing)))
        cp.ok = not missing and cook_a is not None
        if cp.ok:
            cp.input_cost_actual = batches * sum(l.qty * l.pa for l in lines)
            cp.input_cost_std = batches * sum(l.qty * l.ps for l in lines)
            # 按文档公式：出机单价 = 投料成本 ÷ 出锅重
            cp.out_price_actual = cp.input_cost_actual / rec.output_weight
            if p.cooled:
                cp.cooled_price_actual = div(cp.out_price_actual, cool_a)
            if packed and prec is not None:
                pre_price = cp.cooled_price_actual if p.cooled else cp.out_price_actual
                if pre_price is not None and cp.packed_weight:
                    cp.final_price_actual = (pre_price * cp.prepack_weight + bag_fee_total) / cp.packed_weight
            s_out, s_cooled, s_final = evaluate({"all"})
            cp.out_price_std, cp.cooled_price_std, cp.final_price_std = s_out, s_cooled, s_final

            # 差额：成品看成品单价 × 入库量；半成品油看冷后单价 × 冷后重量；否则看出机单价
            if packed:
                pa_, ps_, w = cp.final_price_actual, cp.final_price_std, cp.packed_weight
            elif p.cooled:
                pa_, ps_, w = cp.cooled_price_actual, cp.cooled_price_std, cp.cooled_weight
            else:
                pa_, ps_, w = cp.out_price_actual, cp.out_price_std, rec.output_weight
            if pa_ is not None and ps_ is not None:
                cp.diff_price = pa_ - ps_
                cp.diff_amount = cp.diff_price * w if w is not None else None
                cp.attribution = self.attribute(lines, evaluate, p, packed, prec, w, cp.cool_source)

        cp.trace = {
            "kind": p.ptype,
            "bom": {"id": bom.id, "effective_date": bom.effective_date.isoformat()},
            "batches": js(batches),
            "per_batch": js(per_batch),
            "lines": [{
                "line_no": l.line_no, "name": l.name, "kind": l.kind, "qty": js(l.qty),
                "price_actual": js(l.pa), "price_std": js(l.ps),
                "cost_actual": js(batches * l.qty * l.pa) if l.pa is not None else None,
                **l.info,
            } for l in lines],
            "cook_std_date": std_row.effective_date.isoformat() if std_row else None,
            "bags": bag_detail,
            "bag_per_jin": js(bag_per_jin) if packed else None,
        }
        return cp

    def attribute(self, lines, evaluate, p, packed, prec, weight, cool_source):
        """差额归因：依次把每个环节的实际出率换成标准，记下单价变化。各项之和 = 总差额。"""
        factors: list[tuple[str, str]] = []
        seen = set()
        for l in lines:
            if l.key and l.key not in seen:
                seen.add(l.key)
                label = f"{l.name} 1→2级出率" if l.key.startswith("m:") else f"{l.name} 投料单价（取历史实际价）"
                factors.append((l.key, label))
        factors.append(("cook", "熟制/拌馅出率"))
        if p.cooled and cool_source == "actual":
            factors.append(("cool", "制冷出率"))
        if packed and prec is not None:
            factors.append(("pack", "包装出率"))

        def pick(res):
            out, cooled, final = res
            if packed:
                return final
            return cooled if p.cooled else out

        switched: set[str] = set()
        prev = pick(evaluate(switched))
        result = []
        for key, label in factors:
            switched.add(key)
            cur = pick(evaluate(switched))
            if prev is None or cur is None:
                return None
            d = prev - cur
            if d != 0:
                result.append({"factor": label, "key": key, "per_jin": js(d),
                               "amount": js(d * weight) if weight is not None else None})
            prev = cur
        return result

    # ------------------------------------------------------------ 主流程

    def run(self):
        db = self.db
        results: list[CalcProduct] = []
        for rec in self.production:
            p = self.products.get(rec.product_id)
            if p is None:
                continue
            results.append(self.calc_product(rec, p))
        for pid, prec in self.packing.items():
            if not any(r.product_id == pid for r in self.production):
                self.issue("warning", f"p:{pid}:pack", self.products[pid].name, "有包装记录但当天没有制馅记录")
        for pid in self.cooling:
            if not any(r.product_id == pid for r in self.production):
                self.issue("warning", f"p:{pid}:cool", self.products[pid].name, "有制冷记录但当天没有制馅记录")

        # 处理过但当天没用到的原料也要出出率
        for mid in self.process:
            self.material(mid)

        for r in self.mat_res.values():
            m = r.m
            db.add(CalcMaterial(
                date=self.day, material_id=m.id, qty1=r.qty1, qty2=r.qty2, actual_yield=r.actual,
                std_yield=r.std, yield_source=r.source, price1=r.price1, price2_actual=r.p2a,
                price2_std=r.p2s, used=r.used,
            ))
            key = f"m:{m.id}:process"
            if r.source == "actual":
                if r.std_missing:
                    self.issue("warning", key, m.name, "缺 1→2 级标准出率，标准成本按实际出率计", "process")
                else:
                    self.check_yield(key, m.name, "process", r.actual, r.std, self.th.for_material(m))
            elif r.source == "missing" and r.used:
                self.issue("warning", key, m.name, "当天没有处理记录，也没有标准出率", "process")

        for cp in results:
            db.add(cp)

        # 当日总产量 = 各产品包装入库量 + 麻油产量
        total = ZERO
        for pid, prec in self.packing.items():
            p = self.products[pid]
            if p.ptype == "成品馅":
                total += prec.packed_weight or ZERO
        for rec in self.production:
            if self.products[rec.product_id].ptype == "麻油":
                total += rec.output_weight or ZERO

        energy, warnings = calc_energy_day(db, self.day, total)
        for w in warnings:
            self.issue("warning", w["key"], w["name"], w["message"])
        db.add(CalcEnergy(date=self.day, total_output=total, data=energy))

        # 同一项的提示去重
        seen = set()
        for i in self.issues:
            k = (i.kind, i.item_key, i.message)
            if k not in seen:
                seen.add(k)
                db.add(i)
        db.flush()
        return {"date": self.day.isoformat(), "products": len(results),
                "alerts": sum(1 for i in self.issues if i.kind == "alert"),
                "warnings": sum(1 for i in self.issues if i.kind == "warning")}


# ---------------------------------------------------------------- 重算入口

DAILY_TABLES = [DailyMaterialProcess, DailyProduction, DailyCooling, DailyPacking, MaterialPrice]


def clear_day(db: Session, day: date):
    for model in (CalcMaterial, CalcProduct, CalcIssue, CalcEnergy):
        db.execute(delete(model).where(model.date == day))


def recalc_day(db: Session, day: date) -> dict:
    clear_day(db, day)
    db.flush()
    return DayCalc(db, day).run()


def data_dates(db: Session, start: date | None = None, end: date | None = None) -> list[date]:
    """所有有录入数据的日期（含抄表），升序。"""
    from ..models import MeterReading

    dates: set[date] = set()
    for model in DAILY_TABLES + [MeterReading]:
        stmt = select(model.date).distinct()
        if start:
            stmt = stmt.where(model.date >= start)
        if end:
            stmt = stmt.where(model.date <= end)
        dates.update(db.scalars(stmt))
    return sorted(dates)


def recalc_from(db: Session, start: date | None = None) -> dict:
    """从某天起往后全部重算。

    跨天依赖：半成品油取之前最近一次的单价，麻油取前 7 天，所以改了某天要把之后的日期都重算一遍。
    每天的数据量很小，全量往后重算最稳妥。
    """
    dates = data_dates(db, start)
    # 清掉已经没有录入数据的日期的旧结果
    stale = select(CalcEnergy.date)
    if start:
        stale = stale.where(CalcEnergy.date >= start)
    for d in set(db.scalars(stale)) - set(dates):
        clear_day(db, d)
    out = [recalc_day(db, d) for d in dates]
    db.commit()
    return {"days": len(out), "from": dates[0].isoformat() if dates else None,
            "to": dates[-1].isoformat() if dates else None,
            "alerts": sum(o["alerts"] for o in out), "warnings": sum(o["warnings"] for o in out)}


def first_calc_date(db: Session) -> date | None:
    return db.scalar(select(func.min(CalcEnergy.date)))
