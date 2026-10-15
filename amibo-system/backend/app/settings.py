"""全局设置。待确认事项都做成设置项，工厂答复后改设置即可，不改程序。"""
from sqlalchemy.orm import Session

from .models import Setting

DEFAULTS = {
    # 偏差预警的全局默认阈值（百分点）
    "global_threshold": ("3", "偏差预警全局默认阈值（百分点）"),
    # 偏差超过这个值视为疑似录错，额外提示
    "suspect_pp": ("30", "偏差超过多少百分点提示“疑似录错”"),
    # 麻油投料单价口径：rolling7 = 前 7 天按产量加权平均；prev_week = 上一自然周（周一至周日）按产量加权平均
    "sesame_rule": ("rolling7", "麻油投料单价口径（rolling7 前7天加权 / prev_week 上一自然周加权）"),
    "factory_name": ("", "工厂名称（报表抬头）"),
}


def get_setting(db: Session, key: str) -> str:
    row = db.get(Setting, key)
    if row is not None:
        return row.value
    return DEFAULTS[key][0]


def all_settings(db: Session) -> list[dict]:
    return [
        {"key": k, "value": get_setting(db, k), "label": label, "default": default}
        for k, (default, label) in DEFAULTS.items()
    ]


def set_setting(db: Session, key: str, value: str):
    if key not in DEFAULTS:
        raise KeyError(key)
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
