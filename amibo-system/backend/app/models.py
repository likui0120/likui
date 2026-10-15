"""数据表定义。

三类表：
- 基础资料：会变的资料都带生效日期（effective_date），按版本保存，不覆盖历史。
- 每日录入：统计分析员每天录入的称重、抄表数据。
- 计算结果：每次重算某一天时整天替换，带溯源信息。
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, Dec

# ---------------------------------------------------------------- 常量

MATERIAL_CATEGORIES = ["蔬菜", "泡发", "酱腌", "肉", "调料", "干调", "水", "芝麻", "其他"]
PRODUCT_TYPES = ["成品馅", "半成品油", "麻油"]
TEAMS = ["热加工", "拌馅组", "烧麦豆沙组", "麻油车间"]
ENERGIES = {"gas": ("燃气", "Nm³"), "water": ("水", "吨"), "elec": ("电", "度")}
# 计入方式：+ 计入，- 扣减，ref 参考（只记录不进合计），空 不计入
INCLUDE_MODES = ["+", "-", "ref", ""]
STAGES = {"process": "1→2级", "cook": "熟制/拌馅", "cool": "制冷", "pack": "包装", "oil": "麻油"}


# ---------------------------------------------------------------- 基础资料

class Material(Base):
    """原料（含干调、水、芝麻）。"""

    __tablename__ = "material"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    category: Mapped[str] = mapped_column(String(16), default="其他")
    needs_process: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text)


class MaterialStdYield(Base):
    """原料 1→2 级标准出率（带生效日期）。"""

    __tablename__ = "material_std_yield"
    __table_args__ = (UniqueConstraint("material_id", "effective_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id", ondelete="CASCADE"))
    effective_date: Mapped[date] = mapped_column(Date)
    std_yield: Mapped[object] = mapped_column(Dec)


class MaterialPrice(Base):
    """原料 1 级单价（元/斤），每天从 T+ 导出文件导入。"""

    __tablename__ = "material_price"
    __table_args__ = (UniqueConstraint("material_id", "date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date, index=True)
    price: Mapped[object] = mapped_column(Dec)
    source: Mapped[str | None] = mapped_column(String(255))


class SeasoningPrice(Base):
    """干调单价（元/斤），带生效日期。干调是类别为“干调”的原料。"""

    __tablename__ = "seasoning_price"
    __table_args__ = (UniqueConstraint("material_id", "effective_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id", ondelete="CASCADE"))
    effective_date: Mapped[date] = mapped_column(Date)
    price: Mapped[object] = mapped_column(Dec)


class Product(Base):
    """产品：成品馅、半成品油、麻油。"""

    __tablename__ = "product"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    ptype: Mapped[str] = mapped_column(String(16), default="成品馅")
    team: Mapped[str] = mapped_column(String(16), default="热加工")
    cooled: Mapped[bool] = mapped_column(Boolean, default=False)
    packed: Mapped[bool] = mapped_column(Boolean, default=True)
    # 生馅/熟馅仅用于说明；包装前重量默认取上一环节产出
    unit_weight: Mapped[object | None] = mapped_column(Dec)  # 预留：每袋/盒斤数
    # 半成品油、麻油取不到历史实际单价时用的标准单价（元/斤）
    fallback_price: Mapped[object | None] = mapped_column(Dec)
    # 麻油：用哪种原料（芝麻）
    source_material_id: Mapped[int | None] = mapped_column(ForeignKey("material.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text)


class ProductStdYield(Base):
    """产品各环节标准出率（带生效日期）。麻油的“熟制”出率即麻油出率。"""

    __tablename__ = "product_std_yield"
    __table_args__ = (UniqueConstraint("product_id", "effective_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"))
    effective_date: Mapped[date] = mapped_column(Date)
    cook_yield: Mapped[object | None] = mapped_column(Dec)
    cool_yield: Mapped[object | None] = mapped_column(Dec)
    pack_yield: Mapped[object | None] = mapped_column(Dec)


class Bom(Base):
    """BOM 版本。一个产品同一时间只有一个有效 BOM。"""

    __tablename__ = "bom"
    __table_args__ = (UniqueConstraint("product_id", "effective_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"))
    effective_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    lines: Mapped[list["BomLine"]] = relationship(
        back_populates="bom", cascade="all, delete-orphan", order_by="BomLine.line_no"
    )


class BomLine(Base):
    """BOM 行：每锅（每机）投多少斤。投料是原料（含干调、水）或产品（半成品油、麻油）。"""

    __tablename__ = "bom_line"
    id: Mapped[int] = mapped_column(primary_key=True)
    bom_id: Mapped[int] = mapped_column(ForeignKey("bom.id", ondelete="CASCADE"))
    line_no: Mapped[int] = mapped_column(Integer)
    material_id: Mapped[int | None] = mapped_column(ForeignKey("material.id"))
    input_product_id: Mapped[int | None] = mapped_column(ForeignKey("product.id"))
    qty: Mapped[object] = mapped_column(Dec)
    note: Mapped[str | None] = mapped_column(String(255))
    bom: Mapped[Bom] = relationship(back_populates="lines")


class PackSpec(Base):
    """包装规格。"""

    __tablename__ = "pack_spec"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PackSpecVersion(Base):
    """包装规格的每袋斤数与袋费（元/袋），带生效日期。"""

    __tablename__ = "pack_spec_version"
    __table_args__ = (UniqueConstraint("spec_id", "effective_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    spec_id: Mapped[int] = mapped_column(ForeignKey("pack_spec.id", ondelete="CASCADE"))
    effective_date: Mapped[date] = mapped_column(Date)
    bag_weight: Mapped[object] = mapped_column(Dec)
    fee: Mapped[object] = mapped_column(Dec)


class Meter(Base):
    """计量表。"""

    __tablename__ = "meter"
    id: Mapped[int] = mapped_column(primary_key=True)
    energy: Mapped[str] = mapped_column(String(8))  # gas / water / elec
    name: Mapped[str] = mapped_column(String(128))
    sort: Mapped[int] = mapped_column(Integer, default=0)


class MeterVersion(Base):
    """计量表配置（倍率、计入方式），带生效日期。改配置不改程序。"""

    __tablename__ = "meter_version"
    __table_args__ = (UniqueConstraint("meter_id", "effective_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    meter_id: Mapped[int] = mapped_column(ForeignKey("meter.id", ondelete="CASCADE"))
    effective_date: Mapped[date] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(8), default="reading")  # reading 读数差 / direct 直接填用量
    factor: Mapped[object] = mapped_column(Dec, default=1)  # 用量 = 读数差 × factor
    factor_text: Mapped[str | None] = mapped_column(String(64))  # 显示用，如“÷1000×80”
    plant: Mapped[str] = mapped_column(String(4), default="+")
    workshop: Mapped[str] = mapped_column(String(4), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(255))


class EnergyPrice(Base):
    """能源未税单价，带生效日期。"""

    __tablename__ = "energy_price"
    __table_args__ = (UniqueConstraint("energy", "effective_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    energy: Mapped[str] = mapped_column(String(8))
    effective_date: Mapped[date] = mapped_column(Date)
    price: Mapped[object] = mapped_column(Dec)


class AlertThreshold(Base):
    """预警阈值（百分点）。

    scope：
    - global：全局默认
    - category：某类原料（如蔬菜、泡发）
    - material：某个原料
    - stage：某个产品环节（所有产品）
    - product_stage：某个产品的某个环节
    优先级：material > category > global；product_stage > stage > global。
    """

    __tablename__ = "alert_threshold"
    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(16))
    category: Mapped[str | None] = mapped_column(String(16))
    material_id: Mapped[int | None] = mapped_column(ForeignKey("material.id", ondelete="CASCADE"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"))
    stage: Mapped[str | None] = mapped_column(String(16))
    value: Mapped[object] = mapped_column(Dec)


class AttrVersion(Base):
    """原料、产品里影响计算的属性的版本（带生效日期）。

    原料：needs_process、category；产品：ptype、team、cooled、packed、source_material_id。
    某个原料/产品一旦有版本，计算某天时就用当天有效的版本；没有版本就用资料表里的当前值。
    资料表本身始终保存最新一版的值。
    """

    __tablename__ = "attr_version"
    __table_args__ = (UniqueConstraint("entity", "entity_id", "effective_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entity: Mapped[str] = mapped_column(String(16))  # material / product
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    effective_date: Mapped[date] = mapped_column(Date)
    data: Mapped[dict] = mapped_column(JSON)


class ChangeLog(Base):
    """基础资料修改日志：改了什么、改前改后、从哪天起影响。用于追查历史结果为什么变了。"""

    __tablename__ = "change_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    table: Mapped[str] = mapped_column(String(32))
    row_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))  # create / update / delete
    old: Mapped[dict | None] = mapped_column(JSON)
    new: Mapped[dict | None] = mapped_column(JSON)
    affect_from: Mapped[date | None] = mapped_column(Date)  # 影响从哪天起的结果（空 = 全部历史）
    note: Mapped[str | None] = mapped_column(Text)


class Setting(Base):
    """全局设置（键值）。"""

    __tablename__ = "setting"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


# ---------------------------------------------------------------- 每日录入

class DailyMaterialProcess(Base):
    """原料处理：1 级领用量、2 级称重（斤）。"""

    __tablename__ = "daily_material_process"
    __table_args__ = (UniqueConstraint("date", "material_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id"))
    qty1: Mapped[object] = mapped_column(Dec)
    qty2: Mapped[object] = mapped_column(Dec)


class DailyProduction(Base):
    """制馅：锅数/机数、出锅重或出机重（斤）。麻油用 qty_in 记芝麻用量。"""

    __tablename__ = "daily_production"
    __table_args__ = (UniqueConstraint("date", "product_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    batches: Mapped[object | None] = mapped_column(Dec)
    qty_in: Mapped[object | None] = mapped_column(Dec)  # 麻油：芝麻用量
    output_weight: Mapped[object] = mapped_column(Dec)


class DailyCooling(Base):
    """制冷：打冷出机重（斤）。"""

    __tablename__ = "daily_cooling"
    __table_args__ = (UniqueConstraint("date", "product_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    cooled_weight: Mapped[object] = mapped_column(Dec)


class DailyPacking(Base):
    """包装：包装入库量（斤）；包装前重量可手工覆盖，默认取上一环节产出。"""

    __tablename__ = "daily_packing"
    __table_args__ = (UniqueConstraint("date", "product_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    packed_weight: Mapped[object] = mapped_column(Dec)
    prepack_weight: Mapped[object | None] = mapped_column(Dec)
    bags: Mapped[list["DailyPackingBag"]] = relationship(cascade="all, delete-orphan")


class DailyPackingBag(Base):
    """包装：各规格袋数。"""

    __tablename__ = "daily_packing_bag"
    id: Mapped[int] = mapped_column(primary_key=True)
    packing_id: Mapped[int] = mapped_column(ForeignKey("daily_packing.id", ondelete="CASCADE"))
    spec_id: Mapped[int] = mapped_column(ForeignKey("pack_spec.id"))
    bags: Mapped[object] = mapped_column(Dec)


class MeterReading(Base):
    """抄表：本期读数（光伏等直接填用量的表填当日用量）。换表当天填旧表最终读数和新表起始读数。"""

    __tablename__ = "meter_reading"
    __table_args__ = (UniqueConstraint("date", "meter_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    meter_id: Mapped[int] = mapped_column(ForeignKey("meter.id", ondelete="CASCADE"))
    reading: Mapped[object] = mapped_column(Dec)
    old_final: Mapped[object | None] = mapped_column(Dec)
    new_start: Mapped[object | None] = mapped_column(Dec)


class AnomalyNote(Base):
    """异常项的原因备注。"""

    __tablename__ = "anomaly_note"
    __table_args__ = (UniqueConstraint("date", "item_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    item_key: Mapped[str] = mapped_column(String(128))
    note: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


# ---------------------------------------------------------------- 计算结果

class CalcMaterial(Base):
    """原料当日出率与 2 级单价。"""

    __tablename__ = "calc_material"
    __table_args__ = (UniqueConstraint("date", "material_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id", ondelete="CASCADE"))
    qty1: Mapped[object | None] = mapped_column(Dec)
    qty2: Mapped[object | None] = mapped_column(Dec)
    actual_yield: Mapped[object | None] = mapped_column(Dec)
    std_yield: Mapped[object | None] = mapped_column(Dec)
    yield_source: Mapped[str] = mapped_column(String(8))  # actual / std / fixed / missing
    price1: Mapped[object | None] = mapped_column(Dec)
    price2_actual: Mapped[object | None] = mapped_column(Dec)
    price2_std: Mapped[object | None] = mapped_column(Dec)
    used: Mapped[bool] = mapped_column(Boolean, default=False)  # 当天有产品用到
    # 计算当天用的属性（报表按这个归类，不随资料后来的修改变化）
    category: Mapped[str | None] = mapped_column(String(16))
    needs_process: Mapped[bool | None] = mapped_column(Boolean)
    loss_amount: Mapped[object | None] = mapped_column(Dec)  # 2 级称重为 0（全损）时损失的原料成本（元）


class CalcProduct(Base):
    """产品当日各环节出率、单价（实际/标准）及溯源。"""

    __tablename__ = "calc_product"
    __table_args__ = (UniqueConstraint("date", "product_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"))
    ok: Mapped[bool] = mapped_column(Boolean, default=True)  # 是否算出成本
    input_weight: Mapped[object | None] = mapped_column(Dec)
    input_cost_actual: Mapped[object | None] = mapped_column(Dec)
    input_cost_std: Mapped[object | None] = mapped_column(Dec)
    output_weight: Mapped[object | None] = mapped_column(Dec)
    cook_yield_actual: Mapped[object | None] = mapped_column(Dec)
    cook_yield_std: Mapped[object | None] = mapped_column(Dec)
    out_price_actual: Mapped[object | None] = mapped_column(Dec)
    out_price_std: Mapped[object | None] = mapped_column(Dec)
    cooled_weight: Mapped[object | None] = mapped_column(Dec)
    cool_yield_actual: Mapped[object | None] = mapped_column(Dec)
    cool_yield_std: Mapped[object | None] = mapped_column(Dec)
    cool_source: Mapped[str | None] = mapped_column(String(8))
    cooled_price_actual: Mapped[object | None] = mapped_column(Dec)
    cooled_price_std: Mapped[object | None] = mapped_column(Dec)
    prepack_weight: Mapped[object | None] = mapped_column(Dec)
    packed_weight: Mapped[object | None] = mapped_column(Dec)
    pack_yield_actual: Mapped[object | None] = mapped_column(Dec)
    pack_yield_std: Mapped[object | None] = mapped_column(Dec)
    bag_fee: Mapped[object | None] = mapped_column(Dec)
    final_price_actual: Mapped[object | None] = mapped_column(Dec)
    final_price_std: Mapped[object | None] = mapped_column(Dec)
    diff_price: Mapped[object | None] = mapped_column(Dec)
    diff_amount: Mapped[object | None] = mapped_column(Dec)
    trace: Mapped[dict | None] = mapped_column(JSON)
    attribution: Mapped[list | None] = mapped_column(JSON)
    # 计算当天用的属性（报表按这个归类，不随资料后来的修改变化）
    ptype: Mapped[str | None] = mapped_column(String(16))
    team: Mapped[str | None] = mapped_column(String(16))
    cooled: Mapped[bool | None] = mapped_column(Boolean)
    packed: Mapped[bool | None] = mapped_column(Boolean)
    # 数据质量：status = complete（成品/最终单价算全，全部实测）/ estimated（算出但用了标准值估算）
    #   / partial（只算到中间环节）/ loss（全损）/ none（算不出）；flags 列出原因
    quality: Mapped[dict | None] = mapped_column(JSON)
    loss_amount: Mapped[object | None] = mapped_column(Dec)  # 全损时损失的成本（元）


class CalcIssue(Base):
    """当日异常（偏差超限）与提示（缺数、疑似录错）。"""

    __tablename__ = "calc_issue"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(8))  # alert / warning
    item_key: Mapped[str] = mapped_column(String(128))
    object_name: Mapped[str] = mapped_column(String(128))
    stage: Mapped[str | None] = mapped_column(String(16))
    actual: Mapped[object | None] = mapped_column(Dec)
    std: Mapped[object | None] = mapped_column(Dec)
    dev_pp: Mapped[object | None] = mapped_column(Dec)
    threshold: Mapped[object | None] = mapped_column(Dec)
    message: Mapped[str] = mapped_column(Text)


class CalcEnergy(Base):
    """当日能耗结果。"""

    __tablename__ = "calc_energy"
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    total_output: Mapped[object | None] = mapped_column(Dec)  # 当日总产量（斤）
    data: Mapped[dict] = mapped_column(JSON)
