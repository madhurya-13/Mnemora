"""FastAPI entry point for MNEMORA."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
import logging
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException

from fastapi.responses import JSONResponse

from app.api.chat import router as chat_router
from app.api.conversations import legacy_router as legacy_conversations_router
from app.api.conversations import router as conversations_router
from app.config import settings
from app.database.db import get_db

app = FastAPI(
    title=settings.application_name,
    version=settings.application_version,
    description="A foundation for a personal AI assistant with long-term memory.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(legacy_conversations_router)


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
