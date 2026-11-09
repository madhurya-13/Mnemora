"""Typed schemas for chat requests and conversation management."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    conversation_id: str | None = Field(default=None, min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=settings.chat_max_message_length)
    regenerate: bool = False

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message must contain at least one non-whitespace character.")
        return value


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: str
    response: str
    role: Literal["assistant"] = "assistant"


class ConversationSummary(BaseModel):
    conversation_id: str
    title: str
    updated_at: datetime
    message_count: int


class ConversationDetail(ConversationSummary):
    messages: list[ChatMessage]


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="New chat", min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title must not be blank.")
        return value.strip()


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title must not be blank.")
        return value.strip()


class ChatHealthResponse(BaseModel):
    status: Literal["ready", "not_configured"]
    configured: bool
    model: str


class ErrorResponse(BaseModel):
    error: dict[str, str]
