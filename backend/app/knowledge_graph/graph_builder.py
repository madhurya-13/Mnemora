"""Graph construction: extract, resolve, validate and persist idempotently."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.knowledge_graph import entity_extractor, relationship_extractor
from app.knowledge_graph.graph_merger import find_entity, normalize_entity_name
from app.knowledge_graph.graph_schemas import EntityMention
from app.knowledge_graph.graph_updater import supersede_matching
from app.knowledge_graph.graph_validator import validate_draft
from app.models.adaptive import UserPreference
from app.models.conversation import Conversation
from app.models.graph import (
    GraphEntity,
    GraphHistory,
    GraphRelationship,
    GraphSyncRecord,
)
from app.models.memory import Memory
from app.models.message import Message

logger = logging.getLogger(__name__)

USER_ENTITY_NAME = "User"
USER_ENTITY_TYPE = "person"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_user_entity(db: Session, user_id: UUID) -> GraphEntity:
    entity = find_entity(db, user_id, USER_ENTITY_NAME, USER_ENTITY_TYPE)
    if entity is not None:
        if entity.status != "active":
            entity.status = "active"
            entity.updated_at = _utcnow()
        return entity
    entity = GraphEntity(
        user_id=user_id,
        entity_name=USER_ENTITY_NAME,
        normalized_name=normalize_entity_name(USER_ENTITY_NAME, USER_ENTITY_TYPE),
        entity_type=USER_ENTITY_TYPE,
        description="The MNEMORA user.",
        aliases=["I", "me", "my"],
        confidence=0.99,
        source_memory_ids=[],
        status="active",
    )
    db.add(entity)
    db.flush()
    return entity


def _merge_values(existing: list, additions: list, *, limit: int = 40) -> list:
    merged = list(existing or [])
    for item in additions or []:
        if item not in merged:
            merged.append(item)
    return merged[:limit]


def _entity_for_mention(
    db: Session,
    user_id: UUID,
    mention: EntityMention,
    *,
    memory_id: UUID | None,
    approved: bool,
    now: datetime,
) -> GraphEntity:
    entity = find_entity(db, user_id, mention.name, mention.entity_type)
    target_status = "active" if approved else "pending_review"
    if entity is None:
        entity = GraphEntity(
            user_id=user_id,
            entity_name=mention.name,
            normalized_name=normalize_entity_name(mention.name, mention.entity_type),
            entity_type=mention.entity_type,
            description=mention.description,
            aliases=list(dict.fromkeys([*mention.aliases])),
            confidence=max(settings.graph_min_confidence, min(0.95, mention.confidence)),
            source_memory_ids=[str(memory_id)] if memory_id else [],
            status=target_status,
            first_observed_at=now,
            last_observed_at=now,
        )
        db.add(entity)
        db.flush()
        return entity

    if entity.status == "merged":
        # Follow an explicit merge to the surviving entity.
        while entity is not None and entity.status == "merged" and entity.merged_into_id:
            entity = db.get(GraphEntity, entity.merged_into_id)
        if entity is None:
            raise RuntimeError("Merged entity target is missing.")

    if memory_id and str(memory_id) not in (entity.source_memory_ids or []):
        entity.source_memory_ids = _merge_values(entity.source_memory_ids, [str(memory_id)])
    aliases = list(dict.fromkeys([*(entity.aliases or []), *mention.aliases]))
    if normalize_entity_name(mention.name, entity.entity_type) != entity.normalized_name:
        aliases.append(mention.name)
    entity.aliases = _merge_values([], aliases, limit=settings.graph_max_aliases)
    if approved:
        entity.status = "active"
    elif entity.status not in {"active"}:
        entity.status = "pending_review"
    entity.confidence = max(entity.confidence, min(0.95, mention.confidence))
    entity.last_observed_at = now
    entity.updated_at = now
    if entity.description is None and mention.description:
        entity.description = mention.description
    return entity


def _evidence_entry(
    *,
    now: datetime,
    memory: Memory | None,
    message: Message | None,
    excerpt: str,
    user_confirmed: bool = False,
) -> dict:
    if user_confirmed:
        return {
            "kind": "user",
            "user_confirmed": True,
            "excerpt": excerpt[:240],
            "observed_at": now.isoformat(),
        }
    if memory is not None:
        return {
            "kind": "memory",
            "memory_id": str(memory.memory_id),
            "conversation_id": str(memory.source_conversation_id) if memory.source_conversation_id else None,
            "message_ids": list(memory.source_message_ids or []),
            "excerpt": excerpt[:240],
            "observed_at": now.isoformat(),
        }
    return {
        "kind": "message",
        "message_id": str(message.message_id) if message is not None else None,
        "conversation_id": str(message.conversation_id) if message is not None else None,
        "excerpt": excerpt[:240],
        "observed_at": now.isoformat(),
    }


def _persist_relationship(
    db: Session,
    user_id: UUID,
    draft,
    entity_lookup: dict[tuple[str, str], GraphEntity],
    *,
    memory: Memory | None,
    message: Message | None,
    approved: bool,
    now: datetime,
) -> str | None:
    """Persist one validated draft. Returns created/updated/closed/skipped."""
    if not validate_draft(draft):
        return "skipped"
    source_key = (draft.source_type, normalize_entity_name(draft.source_name, draft.source_type))
    target_key = (draft.target_type, normalize_entity_name(draft.target_name, draft.target_type))
    source = entity_lookup.get(source_key)
    target = entity_lookup.get(target_key)
    if source is None or target is None or source.entity_id == target.entity_id:
        return "skipped"
    if source.status in {"archived", "merged"} or target.status in {"archived", "merged"}:
        return "skipped"

    evidence_memory_ids = [str(memory.memory_id)] if memory is not None else []
    entry = _evidence_entry(now=now, memory=memory, message=message, excerpt=draft.excerpt)
    active_status = "active" if (approved or memory is not None and memory.approval_status == "approved") else "pending_review"

    existing = db.scalar(
        select(GraphRelationship).where(
            GraphRelationship.user_id == user_id,
            GraphRelationship.source_entity_id == source.entity_id,
            GraphRelationship.target_entity_id == target.entity_id,
            GraphRelationship.relationship_type == draft.relationship_type,
            GraphRelationship.status.in_(("active", "pending_review")),
        )
    )

    if draft.temporal_action == "close":
        closed = 0
        if existing is not None:
            existing.status = "historical"
            existing.valid_until = existing.valid_until or now
            existing.updated_at = now
            closed = 1
        else:
            rows = db.scalars(
                select(GraphRelationship).where(
                    GraphRelationship.user_id == user_id,
                    GraphRelationship.source_entity_id == source.entity_id,
                    GraphRelationship.relationship_type == draft.relationship_type,
                    GraphRelationship.status == "active",
                )
            ).all()
            for row in rows:
                row.status = "historical"
                row.valid_until = row.valid_until or now
                row.updated_at = now
                closed += 1
        return "closed" if closed else "skipped"

    if existing is not None:
        existing.evidence_memory_ids = _merge_values(existing.evidence_memory_ids, evidence_memory_ids)
        existing.evidence = _merge_values(existing.evidence or [], [entry], limit=40)
        existing.confidence = max(existing.confidence, draft.confidence)
        existing.description = existing.description or draft.description
        existing.updated_at = now
        if active_status == "active" and existing.status == "pending_review":
            existing.status = "active"
        if not existing.valid_from:
            existing.valid_from = now
        supersede_matching(
            db,
            user_id,
            new_relationship=existing,
            replace_types=draft.replace_types,
            replace_target_types=draft.replace_target_types,
        )
        return "updated"

    status = "historical" if draft.temporal_action == "historical" else active_status
    relationship = GraphRelationship(
        user_id=user_id,
        source_entity_id=source.entity_id,
        target_entity_id=target.entity_id,
        relationship_type=draft.relationship_type,
        description=draft.description,
        confidence=draft.confidence,
        evidence_memory_ids=evidence_memory_ids,
        evidence=[entry],
        valid_from=None if status == "historical" else now,
        valid_until=now if status == "historical" else None,
        status=status,
    )
    db.add(relationship)
    db.flush()
    supersede_matching(
        db,
        user_id,
        new_relationship=relationship,
        replace_types=draft.replace_types,
        replace_target_types=draft.replace_target_types,
    )
    return "created"


def sync_text(
    db: Session,
    user_id: UUID,
    text: str,
    *,
    memory: Memory | None = None,
    message: Message | None = None,
    approved: bool | None = None,
    record_history: bool = True,
) -> dict[str, int]:
    """Extract and persist graph facts from one memory or message."""
    now = _utcnow()
    if approved is None:
        approved = memory is not None and memory.approval_status == "approved"
    user_entity = ensure_user_entity(db, user_id)
    mentions = entity_extractor.extract_entities(text)
    entity_lookup: dict[tuple[str, str], GraphEntity] = {}

    for mention in mentions:
        entity = _entity_for_mention(
            db, user_id, mention, memory_id=memory.memory_id if memory else None,
            approved=bool(approved), now=now,
        )
        entity_lookup[(mention.entity_type, normalize_entity_name(mention.name, mention.entity_type))] = entity
    user_key = (USER_ENTITY_TYPE, user_entity.normalized_name)
    entity_lookup[user_key] = user_entity

    drafts = relationship_extractor.extract_relationships(
        text,
        mentions,
        user_entity=EntityMention(
            name=user_entity.entity_name,
            entity_type=user_entity.entity_type,
            confidence=0.99,
        ),
    )
    counts = {"entities": len(mentions), "created": 0, "updated": 0, "closed": 0, "skipped": 0}
    for draft in drafts:
        outcome = _persist_relationship(
            db, user_id, draft, entity_lookup,
            memory=memory, message=message, approved=bool(approved), now=now,
        )
        counts[outcome] = counts.get(outcome, 0) + 1

    if record_history and (counts["created"] or counts["entities"]):
        db.add(
            GraphHistory(
                user_id=user_id,
                action="sync",
                summary=(
                    f"Graph sync from {'memory' if memory is not None else 'message'}: "
                    f"{counts['entities']} entities, {counts['created']} new relationships."
                ),
                actor="system",
                after={
                    "memory_id": str(memory.memory_id) if memory is not None else None,
                    "message_id": str(message.message_id) if message is not None else None,
                    "counts": counts,
                },
            )
        )
    db.commit()
    return counts


def sync_memory(db: Session, user_id: UUID, memory: Memory) -> dict[str, int]:
    if memory.user_id != user_id:
        raise ValueError("Memory does not belong to this user.")
    counts = sync_text(db, user_id, memory.content, memory=memory)
    if memory.approval_status == "approved" and memory.source_message_ids:
        # Approval activates graph facts that were extracted from the source
        # message while the memory was still pending. Re-evaluating the full
        # message keeps the original conversational context, attaches memory
        # evidence and promotes matching pending relationships.
        message_ids: list[UUID] = []
        for value in memory.source_message_ids:
            try:
                message_ids.append(UUID(str(value)))
            except (TypeError, ValueError):
                continue
        if message_ids:
            messages = db.scalars(
                select(Message)
                .join(Conversation, Conversation.conversation_id == Message.conversation_id)
                .where(
                    Message.message_id.in_(message_ids),
                    Conversation.user_id == user_id,
                    Message.role == "user",
                )
            ).all()
            for message in messages:
                extra = sync_text(
                    db,
                    user_id,
                    message.content,
                    memory=memory,
                    message=message,
                    approved=True,
                    record_history=False,
                )
                for key, value in extra.items():
                    counts[key] = counts.get(key, 0) + value
    return counts


def sync_memory_by_id(db: Session, user_id: UUID, memory_id: UUID) -> dict[str, int]:
    memory = db.scalar(
        select(Memory).where(Memory.memory_id == memory_id, Memory.user_id == user_id)
    )
    if memory is None:
        return {"entities": 0, "created": 0, "updated": 0, "closed": 0, "skipped": 0}
    return sync_memory(db, user_id, memory)


def sync_message(db: Session, user_id: UUID, message_id: UUID) -> dict[str, int]:
    message = db.scalar(
        select(Message)
        .join(Conversation, Conversation.conversation_id == Message.conversation_id)
        .where(
            Message.message_id == message_id,
            Conversation.user_id == user_id,
            Message.role == "user",
        )
    )
    if message is None:
        return {"entities": 0, "created": 0, "updated": 0, "closed": 0, "skipped": 0}
    return sync_text(db, user_id, message.content, message=message, approved=False)


def sync_preferences(db: Session, user_id: UUID) -> int:
    """Link confirmed preferences into the graph without duplicating them."""
    rows = db.scalars(
        select(UserPreference).where(
            UserPreference.user_id == user_id,
            UserPreference.status == "confirmed",
        )
    ).all()
    now = _utcnow()
    user_entity = ensure_user_entity(db, user_id)
    created = 0
    for preference in rows:
        name = preference.description[:200]
        entity = find_entity(db, user_id, name, "preference")
        if entity is None:
            entity = GraphEntity(
                user_id=user_id,
                entity_name=name,
                normalized_name=normalize_entity_name(name, "preference"),
                entity_type="preference",
                description=preference.description,
                aliases=[preference.normalized_key],
                confidence=max(settings.graph_min_confidence, preference.confidence),
                source_memory_ids=list(preference.supporting_memory_ids or []),
                status="active",
                first_observed_at=preference.first_observed_at,
                last_observed_at=preference.last_observed_at,
            )
            db.add(entity)
            db.flush()
            created += 1
        else:
            entity.status = "active"
            entity.confidence = max(entity.confidence, preference.confidence)
            entity.last_observed_at = now
            entity.updated_at = now
        relationship = db.scalar(
            select(GraphRelationship).where(
                GraphRelationship.user_id == user_id,
                GraphRelationship.source_entity_id == user_entity.entity_id,
                GraphRelationship.target_entity_id == entity.entity_id,
                GraphRelationship.relationship_type == "PREFERS",
                GraphRelationship.status.in_(("active", "pending_review")),
            )
        )
        entry = {
            "kind": "user",
            "user_confirmed": True,
            "source": "preference",
            "preference_id": str(preference.preference_id),
            "excerpt": preference.description[:240],
            "observed_at": now.isoformat(),
        }
        if relationship is None:
            db.add(
                GraphRelationship(
                    user_id=user_id,
                    source_entity_id=user_entity.entity_id,
                    target_entity_id=entity.entity_id,
                    relationship_type="PREFERS",
                    description=preference.description,
                    confidence=max(settings.graph_min_confidence, preference.confidence),
                    evidence_memory_ids=list(preference.supporting_memory_ids or []),
                    evidence=[entry],
                    valid_from=preference.first_observed_at,
                    status="active",
                )
            )
            created += 1
        else:
            relationship.status = "active"
            relationship.evidence = _merge_values(relationship.evidence or [], [entry])
            relationship.updated_at = now
    db.commit()
    return created


def rebuild(db: Session, user_id: UUID, *, include_pending: bool = True) -> dict[str, int]:
    """Idempotently re-derive graph facts from memories and confirmed preferences."""
    ensure_user_entity(db, user_id)
    db.commit()
    predicates = [Memory.user_id == user_id]
    if not include_pending:
        predicates.append(Memory.approval_status == "approved")
    else:
        predicates.append(Memory.approval_status.in_(("approved", "pending")))
    memories = db.scalars(
        select(Memory)
        .where(*predicates)
        .order_by(Memory.created_at.asc())
        .limit(settings.graph_max_rebuild_memories)
    ).all()
    processed = 0
    for memory in memories:
        try:
            sync_text(db, user_id, memory.content, memory=memory, record_history=False)
            processed += 1
        except Exception as error:  # one bad memory must not stop the rebuild
            db.rollback()
            logger.warning("Graph rebuild skipped memory (%s).", type(error).__name__)
    preference_links = sync_preferences(db, user_id)
    entities = db.scalar(
        select(func.count()).select_from(GraphEntity).where(GraphEntity.user_id == user_id)
    ) or 0
    relationships = db.scalar(
        select(func.count()).select_from(GraphRelationship).where(GraphRelationship.user_id == user_id)
    ) or 0
    db.add(
        GraphHistory(
            user_id=user_id,
            action="rebuild",
            summary=f"Rebuilt graph from {processed} memories and {preference_links} preference links.",
            actor="system",
            after={
                "memories": processed,
                "preferences": preference_links,
                "entities": entities,
                "relationships": relationships,
            },
        )
    )
    db.commit()
    return {
        "memories_processed": processed,
        "preference_links": preference_links,
        "entities": entities,
        "relationships": relationships,
    }


async def rebuild_user_graph(factory: sessionmaker, user_id: UUID, *, include_pending: bool = True) -> dict:
    with factory() as db:
        return rebuild(db, user_id, include_pending=include_pending)


def enqueue_sync(db: Session, user_id: UUID, source_type: str, source_id: UUID | str) -> None:
    key = str(source_id)
    exists = db.scalar(
        select(GraphSyncRecord.sync_id).where(
            GraphSyncRecord.user_id == user_id,
            GraphSyncRecord.source_type == source_type,
            GraphSyncRecord.source_id == key,
        )
    )
    if exists is None:
        db.add(
            GraphSyncRecord(
                user_id=user_id,
                source_type=source_type,
                source_id=key,
                status="pending",
            )
        )
