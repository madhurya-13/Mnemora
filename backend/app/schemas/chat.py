"""Typed API schemas for persistent conversations and chat."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import settings


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    conversation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=settings.chat_max_message_length)
    regenerate: bool = False

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message must contain at least one non-whitespace character.")
        return value


class ChatMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime
    token_count: int | None = None
    status: Literal["pending", "completed", "failed"]


class ChatResponse(BaseModel):
    conversation_id: UUID
    response: str
    role: Literal["assistant"] = "assistant"


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None
    is_archived: bool
    message_count: int


class ConversationDetail(ConversationSummary):
    messages: list[ChatMessage]


class ConversationList(BaseModel):
    items: list[ConversationSummary]
    total: int
    limit: int
    offset: int


class MessageList(BaseModel):
    items: list[ChatMessage]
    total: int
    limit: int
    offset: int


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="New chat", min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title must not be blank.")
        return value.strip()


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    is_archived: bool | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Title must not be blank.")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def at_least_one_change(self) -> "ConversationUpdateRequest":
        if self.title is None and self.is_archived is None:
            raise ValueError("Provide a title or archive status to update.")
        return self


class ConversationRenameRequest(ConversationUpdateRequest):
    title: str = Field(min_length=1, max_length=120)


class ChatHealthResponse(BaseModel):
    status: Literal["ready", "not_configured"]
    configured: bool
    model: str


class ErrorResponse(BaseModel):
    error: dict[str, str]
