"""Durable background graph construction jobs."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database.db import SessionLocal
from app.knowledge_graph import graph_builder
from app.models.graph import GraphSyncRecord

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _process_record(factory: sessionmaker, sync_id: UUID) -> None:
    with factory() as db:
        claimed = db.execute(
            update(GraphSyncRecord)
            .where(GraphSyncRecord.sync_id == sync_id, GraphSyncRecord.status == "pending")
            .values(status="processing", attempts=GraphSyncRecord.attempts + 1, updated_at=_utcnow())
        )
        if not claimed.rowcount:
            db.rollback()
            return
        db.commit()
        record = db.get(GraphSyncRecord, sync_id)
        if record is None:
            return
        user_id = record.user_id
        source_type = record.source_type
        source_id = record.source_id

    try:
        with factory() as db:
            if source_type == "message":
                graph_builder.sync_message(db, user_id, UUID(source_id))
            elif source_type == "memory":
                graph_builder.sync_memory_by_id(db, user_id, UUID(source_id))
            elif source_type == "rebuild":
                graph_builder.rebuild(db, user_id)
            else:
                raise ValueError(f"Unknown graph sync source type: {source_type}")
        with factory() as db:
            record = db.get(GraphSyncRecord, sync_id)
            if record is not None:
                record.status = "completed"
                record.last_error = None
                record.updated_at = _utcnow()
                db.commit()
    except Exception as error:
        with factory() as db:
            record = db.get(GraphSyncRecord, sync_id)
            if record is not None:
                record.status = (
                    "failed" if record.attempts >= settings.graph_job_max_attempts else "pending"
                )
                record.last_error = type(error).__name__[:120]
                record.updated_at = _utcnow()
                db.commit()
        logger.warning("Graph sync deferred or failed (%s).", type(error).__name__)


async def process_pending_graph_sync(factory: sessionmaker = SessionLocal, *, limit: int = 10) -> int:
    """Process graph construction work without blocking the chat response."""
    if not settings.knowledge_graph_enabled:
        return 0
    with factory() as db:
        ids = db.scalars(
            select(GraphSyncRecord.sync_id)
            .where(
                GraphSyncRecord.status == "pending",
                GraphSyncRecord.attempts < settings.graph_job_max_attempts,
            )
            .order_by(GraphSyncRecord.created_at)
            .limit(limit)
        ).all()
    for sync_id in ids:
        _process_record(factory, sync_id)
    return len(ids)


async def graph_retry_worker() -> None:
    """Resume durable graph jobs after restarts and retry transient failures."""
    with SessionLocal() as db:
        db.execute(
            update(GraphSyncRecord)
            .where(GraphSyncRecord.status == "processing")
            .values(status="pending")
        )
        db.commit()
    while True:
        try:
            await process_pending_graph_sync(SessionLocal)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Graph retry worker pass failed (%s).", type(error).__name__)
        await asyncio.sleep(settings.graph_job_interval_seconds)
