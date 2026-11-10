"""Category-aware time decay used as ranking evidence, never deletion policy."""

from datetime import datetime, timezone

from app.config import settings


def half_life_days(category: str, memory_type: str) -> int:
    if memory_type == "temporary" or category == "temporary":
        return settings.retrieval_half_life_temporary_days
    return {
        "education": settings.retrieval_half_life_education_days,
        "career": settings.retrieval_half_life_career_days,
        "preferences": settings.retrieval_half_life_preferences_days,
        "interests": settings.retrieval_half_life_interests_days,
        "projects": settings.retrieval_half_life_projects_days,
        "goals": settings.retrieval_half_life_goals_days,
        "personal": settings.retrieval_half_life_personal_days,
    }.get(category, settings.retrieval_half_life_other_days)


def recency_score(created_at: datetime, category: str, memory_type: str, *, now: datetime | None = None) -> float:
    current = now or datetime.now(timezone.utc)
    stamp = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (current - stamp).total_seconds() / 86400)
    return 0.5 ** (age_days / half_life_days(category, memory_type))
