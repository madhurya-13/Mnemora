"""FastAPI entry point for MNEMORA."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
import logging
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException

from fastapi.responses import JSONResponse

from app.api.adaptive import router as adaptive_router
from app.api.agents import router as agents_router
from app.api.chat import router as chat_router
from app.api.conversations import legacy_router as legacy_conversations_router
from app.api.conversations import router as conversations_router
from app.api.graph import router as graph_router
from app.api.memories import router as memories_router
from app.api.voice import router as voice_router
from app.config import settings
from app.agents.agent_schemas import (
    AgentConflictError,
    AgentDisabledError,
    AgentError,
    AgentNotFoundError,
    AgentRateLimitError,
    AgentValidationError,
    ToolNotAllowedError,
)
from app.agents.agent_orchestrator import recover_interrupted_executions
from app.database.db import get_db
from app.knowledge_graph.graph_workflow import graph_retry_worker
from app.memory.workflow import retry_worker
from app.services.adaptive_memory.workflow import adaptive_retry_worker


@asynccontextmanager
async def lifespan(_: FastAPI):
    recover_interrupted_executions()
    worker = asyncio.create_task(retry_worker())
    adaptive_worker = asyncio.create_task(adaptive_retry_worker())
    graph_worker = asyncio.create_task(graph_retry_worker())
    try:
        yield
    finally:
        tasks = (worker, adaptive_worker, graph_worker)
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

app = FastAPI(
    title=settings.application_name,
    version=settings.application_version,
    description="A foundation for a personal AI assistant with long-term memory.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(legacy_conversations_router)
app.include_router(adaptive_router)
app.include_router(memories_router)
app.include_router(voice_router)
app.include_router(graph_router)
app.include_router(agents_router)


def _agent_error(status_code: int, code: str):
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"detail": str(exc), "error": {"code": code, "message": str(exc)}},
        )

    return handler


app.add_exception_handler(AgentNotFoundError, _agent_error(404, "agent_not_found"))
app.add_exception_handler(AgentConflictError, _agent_error(409, "agent_conflict"))
app.add_exception_handler(AgentRateLimitError, _agent_error(429, "agent_rate_limited"))
app.add_exception_handler(ToolNotAllowedError, _agent_error(403, "tool_not_allowed"))
app.add_exception_handler(AgentValidationError, _agent_error(422, "agent_invalid_request"))
app.add_exception_handler(AgentDisabledError, _agent_error(503, "agent_disabled"))
app.add_exception_handler(AgentError, _agent_error(400, "agent_error"))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "Please check the request and try again."}})


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).error(
        "Unhandled request error: %s",
        type(exc).__name__,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "The server could not complete this request."}})


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_: Request, exc: SQLAlchemyError) -> JSONResponse:
    logging.getLogger(__name__).error("Database request failed: %s", type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={"error": {"code": "database_unavailable", "message": "Conversation storage is temporarily unavailable."}},
    )


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    return {"application": settings.application_name, "version": settings.application_version, "message": "MNEMORA API is running."}


@app.get("/api/v1/health", tags=["system"])
async def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Conversation storage is unavailable.") from error
    return {"status": "healthy", "application": settings.application_name, "version": settings.application_version}
