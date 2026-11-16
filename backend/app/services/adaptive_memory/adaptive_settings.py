"""Per-user adaptive settings with explicit defaults and no hidden global mutation."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.models.adaptive import AdaptiveSettings


def get_adaptive_settings(db: Session, user_id: UUID, *, create: bool = True) -> AdaptiveSettings:
    row = db.scalar(select(AdaptiveSettings).where(AdaptiveSettings.user_id == user_id))
    if row is not None:
        return row
    row = AdaptiveSettings(
        user_id=user_id,
        preference_confidence_threshold=app_settings.adaptive_preference_confidence_threshold,
        preference_evidence_threshold=app_settings.adaptive_preference_evidence_threshold,
        pattern_evidence_threshold=app_settings.adaptive_pattern_evidence_threshold,
    )
    if create:
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def update_adaptive_settings(db: Session, user_id: UUID, changes: dict) -> AdaptiveSettings:
    row = get_adaptive_settings(db, user_id)
    for key, value in changes.items():
        if value is not None and hasattr(row, key):
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row
