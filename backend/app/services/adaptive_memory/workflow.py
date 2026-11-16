"""Durable background processing for adaptive-learning jobs."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database.db import SessionLocal
from app.models.adaptive import AdaptiveProcessingJob
from app.services.adaptive_memory import adaptive_engine

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _process_job(factory: sessionmaker, job_id: UUID) -> None:
    with factory() as db:
        claimed = db.execute(
            update(AdaptiveProcessingJob)
            .where(AdaptiveProcessingJob.job_id == job_id, AdaptiveProcessingJob.status == "pending")
            .values(status="processing", attempts=AdaptiveProcessingJob.attempts + 1, updated_at=_utcnow())
        )
        if not claimed.rowcount:
            return
        job = db.get(AdaptiveProcessingJob, job_id)
        if job is None:
            db.rollback()
            return
        user_id = job.user_id
        conversation_id = job.conversation_id
        user_message_id = job.user_message_id
        assistant_message_id = job.assistant_message_id
        db.commit()

    try:
        with factory() as db:
            if settings.adaptive_processing_enabled:
                adaptive_engine.observe_turn(
                    db,
                    user_id,
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                )
            job = db.get(AdaptiveProcessingJob, job_id)
            if job:
                job.status = "completed"
                job.last_error = None
                job.updated_at = _utcnow()
                db.commit()
    except Exception as error:
        with factory() as db:
            job = db.get(AdaptiveProcessingJob, job_id)
            if job:
                job.status = "failed" if job.attempts >= settings.adaptive_job_max_attempts else "pending"
                job.last_error = type(error).__name__[:100]
                job.updated_at = _utcnow()
                db.commit()
        logger.warning("Adaptive processing deferred or failed (%s).", type(error).__name__)


async def process_adaptive_jobs(factory: sessionmaker = SessionLocal, *, limit: int = 10) -> int:
    if not settings.adaptive_processing_enabled:
        return 0
    with factory() as db:
        ids = db.scalars(
            select(AdaptiveProcessingJob.job_id)
            .where(
                AdaptiveProcessingJob.status == "pending",
                AdaptiveProcessingJob.attempts < settings.adaptive_job_max_attempts,
            )
            .order_by(AdaptiveProcessingJob.created_at)
            .limit(limit)
        ).all()
    processed = 0
    for job_id in ids:
        await _process_job(factory, job_id)
        processed += 1
    return processed


async def process_user_adaptive_jobs(factory: sessionmaker, user_id: UUID, *, limit: int = 10) -> int:
    if not settings.adaptive_processing_enabled:
        return 0
    with factory() as db:
        ids = db.scalars(
            select(AdaptiveProcessingJob.job_id)
            .where(
                AdaptiveProcessingJob.user_id == user_id,
                AdaptiveProcessingJob.status == "pending",
                AdaptiveProcessingJob.attempts < settings.adaptive_job_max_attempts,
            )
            .order_by(AdaptiveProcessingJob.created_at)
            .limit(limit)
        ).all()
    processed = 0
    for job_id in ids:
        await _process_job(factory, job_id)
        processed += 1
    return processed


async def adaptive_retry_worker() -> None:
    with SessionLocal() as db:
        db.execute(
            update(AdaptiveProcessingJob)
            .where(AdaptiveProcessingJob.status == "processing")
            .values(status="pending")
        )
        db.commit()
    while True:
        try:
            await process_adaptive_jobs(SessionLocal)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Adaptive retry worker pass failed (%s).", type(error).__name__)
        await asyncio.sleep(settings.adaptive_job_interval_seconds)
