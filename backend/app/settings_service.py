"""运行时可改的服务端配置（弱位点平均质量下限）。

运维通过 API 修改后持久化到 app_settings 表；流水线与重算入口统一从这里读取，
审计员只有读取权限。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings as default_settings
from app.models import AppSetting

WEAK_FLOOR_KEY = "weak_quality_floor"

# 允许的下限范围，避免误填无意义值
MIN_FLOOR = 0.0
MAX_FLOOR = 93.0


def get_weak_quality_floor(db: Session) -> float:
    row = db.query(AppSetting).filter(AppSetting.key == WEAK_FLOOR_KEY).first()
    if row is not None:
        try:
            return float(row.value)
        except ValueError:
            pass
    return float(default_settings.weak_quality_floor)


def set_weak_quality_floor(db: Session, value: float) -> float:
    value = float(value)
    if not (MIN_FLOOR <= value <= MAX_FLOOR):
        raise ValueError(f"平均质量下限须在 {MIN_FLOOR}~{MAX_FLOOR} 之间")
    row = db.query(AppSetting).filter(AppSetting.key == WEAK_FLOOR_KEY).first()
    if row is None:
        row = AppSetting(key=WEAK_FLOOR_KEY, value=str(value))
        db.add(row)
    else:
        row.value = str(value)
    db.commit()
    return value
