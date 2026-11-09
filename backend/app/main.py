"""FastAPI entry point for MNEMORA."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
import logging

from fastapi.responses import JSONResponse

from app.api.chat import router as chat_router
from app.config import settings

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


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    return {"application": settings.application_name, "version": settings.application_version, "message": "MNEMORA API is running."}


@app.get("/api/v1/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "healthy", "application": settings.application_name, "version": settings.application_version}
