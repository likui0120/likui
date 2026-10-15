"""导入批次记录：每次确认导入 T+ 单价记一条，能看到导入了什么、覆盖了什么，并能撤销。

单独放一个文件，不和 models.py 混在一起；main.py 在建表前 import 它。
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class ImportBatch(Base):
    __tablename__ = "import_batch"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="tplus")
    date: Mapped[date] = mapped_column(Date, index=True)  # 单价记到哪一天
    filename: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    price_col: Mapped[str | None] = mapped_column(String(60))  # 用的是哪一列单价
    matched: Mapped[int] = mapped_column(Integer, default=0)
    unmatched: Mapped[int] = mapped_column(Integer, default=0)
    flagged: Mapped[int] = mapped_column(Integer, default=0)  # 需要核对的行数
    # [{material_id, name, old_price, old_source, new_price}]，撤销时按它恢复
    detail: Mapped[list] = mapped_column(JSON, default=list)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime)
