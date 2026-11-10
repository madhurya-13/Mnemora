"""Owner-scoped persistent conversation management endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.models.user import User
from app.schemas.chat import (
    ConversationCreateRequest,
    ConversationDetail,
    ConversationList,
    ConversationRenameRequest,
    ConversationSummary,
    ConversationUpdateRequest,
    MessageList,
)
from app.services import conversation_service
from app.services.conversation_service import ConversationNotFoundError
from app.services.session_service import get_current_user

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])
legacy_router = APIRouter(prefix="/api/v1/chat/conversations", tags=["conversations-compat"])


def _not_found(error: ConversationNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")


@router.post("", response_model=ConversationDetail, status_code=status.HTTP_201_CREATED)
@legacy_router.post("", response_model=ConversationDetail, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConversationDetail:
    return conversation_service.create_conversation(db, user.user_id, payload.title)


@router.get("", response_model=ConversationList)
def list_conversations(
    archived: bool | None = False,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConversationList:
    return conversation_service.list_conversations(
        db, user.user_id, archived=archived, limit=limit, offset=offset
    )


@legacy_router.get("", response_model=list[ConversationSummary])
def list_conversations_legacy(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ConversationSummary]:
    page = conversation_service.list_conversations(
        db, user.user_id, archived=False, limit=100, offset=0
    )
    return page.items


@router.get("/{conversation_id}", response_model=ConversationDetail)
@legacy_router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConversationDetail:
    try:
        return conversation_service.get_conversation(db, user.user_id, conversation_id)
    except ConversationNotFoundError as error:
        raise _not_found(error)


@router.get("/{conversation_id}/messages", response_model=MessageList)
def get_conversation_messages(
    conversation_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MessageList:
    try:
        return conversation_service.get_messages(
            db, user.user_id, conversation_id, limit=limit, offset=offset
        )
    except ConversationNotFoundError as error:
        raise _not_found(error)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConversationSummary:
    try:
        return conversation_service.update_conversation(
            db,
            user.user_id,
            conversation_id,
            title=payload.title,
            is_archived=payload.is_archived,
        )
    except ConversationNotFoundError as error:
        raise _not_found(error)


@legacy_router.patch("/{conversation_id}", response_model=ConversationSummary)
def rename_conversation_legacy(
    conversation_id: UUID,
    payload: ConversationRenameRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConversationSummary:
    try:
        return conversation_service.update_conversation(
            db, user.user_id, conversation_id, title=payload.title
        )
    except ConversationNotFoundError as error:
        raise _not_found(error)


@legacy_router.delete("/{conversation_id}/messages", response_model=ConversationDetail)
def clear_conversation_legacy(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConversationDetail:
    try:
        return conversation_service.clear_conversation(db, user.user_id, conversation_id)
    except ConversationNotFoundError as error:
        raise _not_found(error)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
@legacy_router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    try:
        conversation_service.delete_conversation(db, user.user_id, conversation_id)
    except ConversationNotFoundError as error:
        raise _not_found(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
