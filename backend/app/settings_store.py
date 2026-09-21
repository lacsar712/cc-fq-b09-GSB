"""Runtime-adjustable QC settings backed by the app_settings table.

Resolution order for the weak-position threshold:
DB row (set by bioops via API) -> env/default from app.config.settings.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting

WEAK_THRESHOLD_KEY = "weak_quality_threshold"


def get_weak_threshold(db: Session) -> float:
    """Current effective weak-position threshold (mean quality lower bound)."""
    row = db.get(AppSetting, WEAK_THRESHOLD_KEY)
    if row is not None:
        try:
            return float(row.value)
        except (TypeError, ValueError):
            pass
    return settings.weak_quality_threshold


def set_weak_threshold(db: Session, value: float, username: str) -> AppSetting:
    """Persist a new threshold (bioops only, enforced at the API layer)."""
    row = db.get(AppSetting, WEAK_THRESHOLD_KEY)
    now = datetime.now(timezone.utc)
    if row is None:
        row = AppSetting(key=WEAK_THRESHOLD_KEY, value=str(value))
        db.add(row)
    else:
        row.value = str(value)
    row.updated_by = username
    row.updated_at = now
    db.commit()
    db.refresh(row)
    return row
