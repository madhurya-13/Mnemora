"""Owner-scoped memory lifecycle, approval, statistics and semantic search API."""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database.db import SessionLocal, get_db
from app.memory import retriever, service, workflow
from app.memory.embeddings import EmbeddingConfigurationError, EmbeddingServiceError
from app.memory.service import MemoryConflictError, MemoryNotFoundError, MemoryUnsafeContentError
from app.models.conversation import Conversation
from app.models.memory import Memory, MemoryConflict, MemoryExtractionJob, MemoryVectorOutbox
from app.models.message import Message
from app.models.user import User
from app.schemas.memory import (
    ApprovalStatus,
    MemoryCategory,
    MemoryCreateRequest,
    MemoryConflictPage,
    MemoryConflictResolveRequest,
    MemoryConflictResponse,
    MemoryHistoryResponse,
    MemoryPage,
    MemoryResponse,
    MemoryRetrieveItem,
    MemoryRetrieveRequest,
    MemoryRetrieveResponse,
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
    MemoryStats,
    MemoryUpdateRequest,
    QueryAnalysisResponse,
    RetrievalStatsResponse,
)
from app.services.session_service import get_current_user
from app.retrieval import hybrid_retriever, query_analyzer

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])


def _factory(db: Session) -> sessionmaker:
    return sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False, expire_on_commit=False)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Memory not found.")


def _safe_embedding_error(error: Exception) -> HTTPException:
    if isinstance(error, EmbeddingConfigurationError):
        return HTTPException(status_code=503, detail=str(error))
    if isinstance(error, EmbeddingServiceError):
        return HTTPException(status_code=502, detail=str(error))
    return HTTPException(status_code=503, detail="Semantic memory service is temporarily unavailable.")


def _validate_sources(db: Session, user_id: UUID, payload: MemoryCreateRequest) -> None:
    if payload.source_conversation_id:
        owned = db.scalar(select(Conversation.conversation_id).where(
            Conversation.conversation_id == payload.source_conversation_id,
            Conversation.user_id == user_id,
        ))
        if not owned:
            raise HTTPException(status_code=404, detail="Source conversation not found.")
    if payload.source_message_ids:
        found = db.scalars(
            select(Message.message_id)
            .join(Conversation, Message.conversation_id == Conversation.conversation_id)
            .where(Message.message_id.in_(payload.source_message_ids), Conversation.user_id == user_id)
        ).all()
        if len(set(found)) != len(set(payload.source_message_ids)):
            raise HTTPException(status_code=404, detail="One or more source messages were not found.")


def _conflict_response(db: Session, conflict: MemoryConflict, user_id: UUID) -> MemoryConflictResponse | None:
    existing = db.scalar(select(Memory).where(
        Memory.memory_id == conflict.existing_memory_id, Memory.user_id == user_id,
    ))
    candidate = db.scalar(select(Memory).where(
        Memory.memory_id == conflict.new_memory_id, Memory.user_id == user_id,
    ))
    if existing is None or candidate is None:
        return None
    return MemoryConflictResponse(
        conflict_id=conflict.conflict_id, conflict_type=conflict.conflict_type,
        status=conflict.status, summary=conflict.summary, resolution=conflict.resolution,
        created_at=conflict.created_at, resolved_at=conflict.resolved_at,
        existing_memory=existing, new_memory=candidate,
    )


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Memory:
    _validate_sources(db, user.user_id, payload)
    try:
        memory = await service.add_candidate(
            db, user.user_id, payload, source="user",
            source_conversation_id=payload.source_conversation_id,
            source_message_ids=payload.source_message_ids,
            auto_save=settings.memory_auto_save,
        )
        if memory.vector_sync_status == "pending":
            await service.process_vector_outbox(_factory(db))
            db.refresh(memory)
        return memory
    except MemoryUnsafeContentError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("", response_model=MemoryPage)
def list_memories(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    category: MemoryCategory | None = None,
    approval_status: ApprovalStatus | None = None,
    sort_by: str = Query(default="updated_at", pattern="^(created_at|updated_at|importance)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MemoryPage:
    items, total = service.list_memories(
        db, user.user_id, limit=limit, offset=offset, category=category,
        approval_status=approval_status, sort_by=sort_by, sort_order=sort_order,
    )
    return MemoryPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/stats", response_model=MemoryStats)
def get_memory_stats(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> MemoryStats:
    return MemoryStats(**service.memory_stats(db, user.user_id))


@router.post("/search", response_model=MemorySearchResponse)
async def search_memories(
    payload: MemorySearchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MemorySearchResponse:
    try:
        results = await retriever.search_memories(
            db, user.user_id, payload.query, top_k=payload.top_k, category=payload.category,
            min_importance=payload.min_importance, date_from=payload.date_from,
            date_to=payload.date_to, sort_by=payload.sort_by,
        )
    except (EmbeddingConfigurationError, EmbeddingServiceError) as error:
        raise _safe_embedding_error(error) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="Semantic memory search is temporarily unavailable.") from error
    return MemorySearchResponse(query=payload.query, results=results)


@router.post("/analyze-query", response_model=QueryAnalysisResponse)
def analyze_memory_query(
    payload: MemorySearchRequest,
    user: User = Depends(get_current_user),
) -> QueryAnalysisResponse:
    del user  # Authentication is required; analysis itself uses no account data.
    return query_analyzer.analyze_query(payload.query)


@router.post("/retrieve", response_model=MemoryRetrieveResponse)
async def retrieve_memories(
    payload: MemoryRetrieveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MemoryRetrieveResponse:
    try:
        result = await hybrid_retriever.retrieve(db, user.user_id, payload.query, top_k=payload.top_k)
    except (EmbeddingConfigurationError, EmbeddingServiceError) as error:
        raise _safe_embedding_error(error) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="Memory retrieval is temporarily unavailable.") from error
    selected = [MemoryRetrieveItem(
        memory=row["memory"], rank=rank, retrieval_reason=row["retrieval_reason"],
        semantic_score=row["semantic_score"], keyword_score=row["keyword_score"],
        importance_score=row["components"]["importance"], confidence_score=row["components"]["confidence"],
        recency_score=row["components"]["recency"], category_score=row["components"]["category"],
        usage_score=row["components"]["usage"], final_score=row["final_score"],
    ) for rank, row in enumerate(result.context["selected"], 1)]
    return MemoryRetrieveResponse(
        query=payload.query, analysis=result.analysis, selected=selected,
        candidate_count=result.candidate_count,
        excluded_count=max(0, result.candidate_count - len(selected)), latency_ms=result.latency_ms,
    )


@router.get("/conflicts", response_model=MemoryConflictPage)
def get_memory_conflicts(
    status_filter: str = Query(default="unresolved", alias="status", pattern="^(unresolved|resolved_kept|resolved_updated|all)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MemoryConflictPage:
    predicates = [MemoryConflict.user_id == user.user_id]
    if status_filter != "all":
        predicates.append(MemoryConflict.status == status_filter)
    conflicts = db.scalars(select(MemoryConflict).where(*predicates).order_by(MemoryConflict.created_at.desc())).all()
    items = [response for conflict in conflicts if (response := _conflict_response(db, conflict, user.user_id)) is not None]
    return MemoryConflictPage(items=items, total=len(items))


@router.post("/conflicts/{conflict_id}/resolve", response_model=MemoryConflictResponse)
async def resolve_memory_conflict(
    conflict_id: UUID,
    payload: MemoryConflictResolveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MemoryConflictResponse:
    try:
        conflict, _ = service.resolve_conflict(
            db, user.user_id, conflict_id, resolution=payload.resolution,
            edited_content=payload.edited_content,
        )
        if payload.resolution in {"accept_update", "edit"}:
            await service.process_vector_outbox(_factory(db))
            db.refresh(conflict)
        response = _conflict_response(db, conflict, user.user_id)
        if response is None:
            raise _not_found()
        return response
    except MemoryNotFoundError as error:
        raise _not_found() from error
    except MemoryConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except MemoryUnsafeContentError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/retrieval-stats", response_model=RetrievalStatsResponse)
def get_retrieval_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RetrievalStatsResponse:
    return RetrievalStatsResponse(**service.retrieval_stats(db, user.user_id))


@router.get("/{memory_id}/history", response_model=list[MemoryHistoryResponse])
def get_memory_history(
    memory_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MemoryHistoryResponse]:
    try:
        return service.memory_history(db, user.user_id, memory_id)
    except MemoryNotFoundError as error:
        raise _not_found() from error


@router.post("/extractions/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_extractions(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    jobs = db.scalars(select(MemoryExtractionJob).where(
        MemoryExtractionJob.user_id == user.user_id,
        MemoryExtractionJob.status == "failed",
    )).all()
    for job in jobs:
        job.status = "pending"
        job.attempts = 0
        job.last_error = None
    db.commit()
    if jobs:
        background_tasks.add_task(workflow.process_pending_jobs, _factory(db))
    return {"queued": len(jobs)}


@router.get("/{memory_id}", response_model=MemoryResponse)
def get_memory(
    memory_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Memory:
    memory = db.scalar(select(Memory).where(Memory.memory_id == memory_id, Memory.user_id == user.user_id))
    if memory is None:
        raise _not_found()
    return memory


@router.put("/{memory_id}", response_model=MemoryResponse)
async def put_memory(
    memory_id: UUID,
    payload: MemoryUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Memory:
    try:
        memory = service.update_memory(db, user.user_id, memory_id, payload.model_dump(exclude_unset=True))
        if memory.vector_sync_status == "pending":
            await service.process_vector_outbox(_factory(db))
            db.refresh(memory)
        return memory
    except MemoryNotFoundError as error:
        raise _not_found() from error
    except MemoryUnsafeContentError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/{memory_id}", status_code=status.HTTP_200_OK)
async def remove_memory(
    memory_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    try:
        needs_cleanup = await service.delete_memory(db, user.user_id, memory_id)
    except MemoryNotFoundError as error:
        raise _not_found() from error
    if needs_cleanup:
        await service.process_vector_outbox(_factory(db))
    pending = db.scalar(select(MemoryVectorOutbox.operation_id).where(
        MemoryVectorOutbox.memory_id == memory_id, MemoryVectorOutbox.user_id == user.user_id
    )) is not None
    return {"deleted": True, "vector_cleanup_pending": pending}


@router.post("/{memory_id}/approve", response_model=MemoryResponse)
async def approve_memory(
    memory_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Memory:
    try:
        memory = await service.approve_memory(db, user.user_id, memory_id)
        await service.process_vector_outbox(_factory(db))
        db.refresh(memory)
        return memory
    except MemoryNotFoundError as error:
        raise _not_found() from error
    except MemoryConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{memory_id}/reject", response_model=MemoryResponse)
def reject_memory(
    memory_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Memory:
    try:
        return service.reject_memory(db, user.user_id, memory_id)
    except MemoryNotFoundError as error:
        raise _not_found() from error
    except MemoryConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
