"""Durable post-chat memory extraction jobs and retry processing."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database.db import SessionLocal
from app.memory import extractor, service
from app.memory.service import MemoryUnsafeContentError
from app.models.memory import MemoryExtractionJob
from app.models.message import Message
from app.schemas.memory import MemoryCandidate

logger = logging.getLogger(__name__)


async def _process_job(factory: sessionmaker, job_id: UUID) -> None:
    with factory() as db:
        claimed = db.execute(
            update(MemoryExtractionJob)
            .where(MemoryExtractionJob.job_id == job_id, MemoryExtractionJob.status == "pending")
            .values(status="processing", attempts=MemoryExtractionJob.attempts + 1, updated_at=datetime.now(timezone.utc))
        )
        if not claimed.rowcount:
            return
        job = db.get(MemoryExtractionJob, job_id)
        if job is None:
            db.rollback()
            return
        user_id = job.user_id
        conversation_id = job.conversation_id
        user_message_id = job.user_message_id
        db.commit()

    try:
        with factory() as db:
            user_message = db.get(Message, user_message_id)
            if user_message is None or user_message.role != "user":
                raise extractor.MemoryExtractionError("The source user message is unavailable.")
            user_text = user_message.content
        candidates = await extractor.extract_memories(user_text)
        for candidate in candidates:
            with factory() as db:
                try:
                    memory = await service.add_candidate(
                        db,
                        user_id,
                        candidate,
                        source="conversation_extraction",
                        source_conversation_id=conversation_id,
                        source_message_ids=[user_message_id],
                        auto_save=settings.memory_auto_save,
                    )
                except MemoryUnsafeContentError:
                    continue
                if memory.approval_status == "approved" and memory.vector_sync_status != "synced":
                    await service.process_vector_outbox(factory)
        with factory() as db:
            job = db.get(MemoryExtractionJob, job_id)
            if job:
                job.status = "completed"
                job.last_error = None
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
    except Exception as error:
        with factory() as db:
            job = db.get(MemoryExtractionJob, job_id)
            if job:
                job.status = "failed" if job.attempts >= settings.memory_extraction_max_attempts else "pending"
                job.last_error = type(error).__name__[:100]
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
        logger.warning("Memory extraction job deferred or failed (%s).", type(error).__name__)


async def process_pending_jobs(factory: sessionmaker = SessionLocal, *, limit: int = 10) -> int:
    """Process the oldest unclaimed jobs; retries are durable and capped."""
    with factory() as db:
        ids = db.scalars(
            select(MemoryExtractionJob.job_id)
            .where(MemoryExtractionJob.status == "pending", MemoryExtractionJob.attempts < settings.memory_extraction_max_attempts)
            .order_by(MemoryExtractionJob.created_at)
            .limit(limit)
        ).all()
    processed = 0
    for job_id in ids:
        await _process_job(factory, job_id)
        processed += 1
    await service.process_vector_outbox(factory)
    return processed


async def retry_worker() -> None:
    """Resume pending durable jobs after restarts and retry transient failures."""
    with SessionLocal() as db:
        db.execute(update(MemoryExtractionJob).where(MemoryExtractionJob.status == "processing").values(status="pending"))
        db.commit()
    while True:
        try:
            await process_pending_jobs(SessionLocal)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Memory retry worker pass failed (%s).", type(error).__name__)
        await asyncio.sleep(30)
