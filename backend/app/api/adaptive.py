"""Adaptive preferences, patterns, feedback, evolution and health API."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database.db import get_db
from app.memory import service as memory_service
from app.memory.service import MemoryNotFoundError, MemoryUnsafeContentError
from app.memory.safety import contains_sensitive_information
from app.models.adaptive import (
    AdaptiveProcessingJob,
    MemoryFeedback,
    MemoryPattern,
    UserPreference,
)
from app.models.memory import Memory
from app.models.user import User
from app.schemas.adaptive import (
    AdaptiveRunResponse,
    AdaptiveSettingsResponse,
    AdaptiveSettingsUpdate,
    EvolutionItem,
    EvolutionPage,
    FeedbackCreateRequest,
    FeedbackInsights,
    FeedbackPage,
    FeedbackResponse,
    LifecycleUpdateRequest,
    MemoryHealthResponse,
    PatternPage,
    PatternResponse,
    PreferenceConfirmRequest,
    PreferencePage,
    PreferenceResponse,
    PreferenceUpdateRequest,
)
from app.schemas.memory import MemoryResponse
from app.services.adaptive_memory import adaptive_engine, memory_decay, pattern_detector
from app.services.adaptive_memory.adaptive_settings import (
    get_adaptive_settings,
    update_adaptive_settings,
)
from app.services.adaptive_memory.feedback_processor import (
    FeedbackConflictError,
    FeedbackNotFoundError,
    FeedbackValidationError,
    insights,
    list_feedback,
    submit_feedback,
)
from app.services.adaptive_memory.memory_evolution import evolution_timeline
from app.services.adaptive_memory.workflow import process_user_adaptive_jobs
from app.services.session_service import get_current_user

router = APIRouter(prefix="/api/v1/memories", tags=["adaptive-memory"])


def _factory(db: Session) -> sessionmaker:
    return sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False, expire_on_commit=False)


def _not_found(kind: str = "Preference") -> HTTPException:
    return HTTPException(status_code=404, detail=f"{kind} not found.")


@router.get("/preferences", response_model=PreferencePage)
def list_preferences(
    status_filter: str | None = Query(default=None, alias="status", pattern="^(candidate|confirmed|rejected|disabled)$"),
    category: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PreferencePage:
    predicates = [UserPreference.user_id == user.user_id]
    if status_filter:
        predicates.append(UserPreference.status == status_filter)
    if category:
        predicates.append(UserPreference.category == category)
    rows = db.scalars(
        select(UserPreference).where(*predicates)
        .order_by(UserPreference.last_observed_at.desc(), UserPreference.created_at.desc())
        .limit(limit).offset(offset)
    ).all()
    total = db.scalar(select(func.count(UserPreference.preference_id)).where(*predicates)) or 0
    return PreferencePage(items=list(rows), total=int(total), limit=limit, offset=offset)


@router.post("/preferences/{preference_id}/confirm", response_model=PreferenceResponse)
def confirm_preference(
    preference_id: UUID,
    payload: PreferenceConfirmRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserPreference:
    preference = db.scalar(select(UserPreference).where(
        UserPreference.preference_id == preference_id,
        UserPreference.user_id == user.user_id,
    ))
    if preference is None:
        raise _not_found()
    description = payload.description.strip() if payload and payload.description else None
    if description and contains_sensitive_information(description):
        raise HTTPException(status_code=422, detail="Preferences cannot contain sensitive information.")
    if description:
        preference.description = description
    preference.status = "confirmed"
    preference.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(preference)
    return preference


@router.put("/preferences/{preference_id}", response_model=PreferenceResponse)
def edit_preference(
    preference_id: UUID,
    payload: PreferenceUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserPreference:
    preference = db.scalar(select(UserPreference).where(
        UserPreference.preference_id == preference_id,
        UserPreference.user_id == user.user_id,
    ))
    if preference is None:
        raise _not_found()
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("description") and contains_sensitive_information(changes["description"]):
        raise HTTPException(status_code=422, detail="Preferences cannot contain sensitive information.")
    for key, value in changes.items():
        if value is not None:
            setattr(preference, key, value)
    db.commit()
    db.refresh(preference)
    return preference


@router.post("/preferences/{preference_id}/reject", response_model=PreferenceResponse)
def reject_preference(
    preference_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserPreference:
    preference = db.scalar(select(UserPreference).where(
        UserPreference.preference_id == preference_id,
        UserPreference.user_id == user.user_id,
    ))
    if preference is None:
        raise _not_found()
    preference.status = "rejected"
    db.commit()
    db.refresh(preference)
    return preference


@router.delete("/preferences/{preference_id}", status_code=status.HTTP_200_OK)
def delete_preference(
    preference_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    preference = db.scalar(select(UserPreference).where(
        UserPreference.preference_id == preference_id,
        UserPreference.user_id == user.user_id,
    ))
    if preference is None:
        raise _not_found()
    db.delete(preference)
    db.commit()
    return {"deleted": True}


@router.get("/patterns", response_model=PatternPage)
def list_patterns(
    status_filter: str | None = Query(default=None, alias="status", pattern="^(candidate|confirmed|dismissed)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PatternPage:
    predicates = [MemoryPattern.user_id == user.user_id]
    if status_filter:
        predicates.append(MemoryPattern.status == status_filter)
    rows = db.scalars(
        select(MemoryPattern).where(*predicates)
        .order_by(MemoryPattern.last_observed_at.desc())
    ).all()
    return PatternPage(items=list(rows), total=len(rows))


@router.post("/patterns/{pattern_id}/confirm", response_model=PatternResponse)
def confirm_pattern(
    pattern_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MemoryPattern:
    pattern = db.scalar(select(MemoryPattern).where(
        MemoryPattern.pattern_id == pattern_id, MemoryPattern.user_id == user.user_id,
    ))
    if pattern is None:
        raise _not_found("Pattern")
    pattern.status = "confirmed"
    db.commit()
    db.refresh(pattern)
    return pattern


@router.post("/patterns/{pattern_id}/dismiss", response_model=PatternResponse)
def dismiss_pattern(
    pattern_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MemoryPattern:
    pattern = db.scalar(select(MemoryPattern).where(
        MemoryPattern.pattern_id == pattern_id, MemoryPattern.user_id == user.user_id,
    ))
    if pattern is None:
        raise _not_found("Pattern")
    pattern.status = "dismissed"
    db.commit()
    db.refresh(pattern)
    return pattern


@router.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def create_feedback(
    payload: FeedbackCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MemoryFeedback:
    try:
        return submit_feedback(db, user.user_id, payload)
    except FeedbackNotFoundError as error:
        raise HTTPException(status_code=404, detail="The feedback target was not found.") from error
    except FeedbackValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except FeedbackConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/feedback", response_model=FeedbackPage)
def get_feedback(
    feedback_type: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FeedbackPage:
    rows, total = list_feedback(db, user.user_id, limit=limit, offset=offset, feedback_type=feedback_type)
    return FeedbackPage(items=rows, total=total, limit=limit, offset=offset)


@router.get("/feedback/insights", response_model=FeedbackInsights)
def feedback_insights(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> FeedbackInsights:
    return FeedbackInsights(**insights(db, user.user_id))


@router.get("/evolution", response_model=EvolutionPage)
def get_evolution(
    memory_id: UUID | None = None,
    change_type: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=100, ge=1, le=300),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EvolutionPage:
    items = evolution_timeline(
        db, user.user_id, memory_id=memory_id, change_type=change_type, limit=limit,
    )
    return EvolutionPage(items=[EvolutionItem(**item) for item in items], total=len(items))


@router.get("/health", response_model=MemoryHealthResponse)
def get_memory_health(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> MemoryHealthResponse:
    return MemoryHealthResponse(**memory_decay.memory_health(db, user.user_id))


@router.get("/adaptive-settings", response_model=AdaptiveSettingsResponse)
def get_settings(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AdaptiveSettingsResponse:
    row = get_adaptive_settings(db, user.user_id)
    return AdaptiveSettingsResponse.model_validate(row)


@router.put("/adaptive-settings", response_model=AdaptiveSettingsResponse)
def put_settings(
    payload: AdaptiveSettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AdaptiveSettingsResponse:
    row = update_adaptive_settings(db, user.user_id, payload.model_dump(exclude_unset=True))
    return AdaptiveSettingsResponse.model_validate(row)


@router.get("/adaptive/status")
def adaptive_status(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    rows = db.execute(
        select(AdaptiveProcessingJob.status, func.count(AdaptiveProcessingJob.job_id))
        .where(AdaptiveProcessingJob.user_id == user.user_id)
        .group_by(AdaptiveProcessingJob.status)
    ).all()
    settings_row = get_adaptive_settings(db, user.user_id)
    return {
        "enabled": settings_row.preference_learning_enabled or settings_row.pattern_detection_enabled,
        "jobs": {status_name: int(count) for status_name, count in rows},
    }


@router.post("/adaptive/process", response_model=AdaptiveRunResponse)
async def process_adaptive(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AdaptiveRunResponse:
    factory = _factory(db)
    jobs = await process_user_adaptive_jobs(factory, user.user_id)
    with factory() as session:
        evaluated = adaptive_engine.evaluate_user(session, user.user_id)
        settings_row = get_adaptive_settings(session, user.user_id)
        patterns = pattern_detector.detect_patterns(
            session, user.user_id, evidence_threshold=settings_row.pattern_evidence_threshold,
        ) if settings_row.pattern_detection_enabled else 0
    return AdaptiveRunResponse(
        processed_jobs=jobs, evaluated_memories=evaluated, detected_patterns=patterns,
    )


@router.post("/{memory_id}/lifecycle", response_model=MemoryResponse)
def change_memory_lifecycle(
    memory_id: UUID,
    payload: LifecycleUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Memory:
    try:
        return memory_service.set_lifecycle_status(db, user.user_id, memory_id, payload.status)
    except MemoryNotFoundError as error:
        raise HTTPException(status_code=404, detail="Memory not found.") from error
    except MemoryUnsafeContentError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
