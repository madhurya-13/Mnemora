"""FastAPI entry point for MNEMORA."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.errors(), "message": "Request validation failed."})


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    return {"application": settings.application_name, "version": settings.application_version, "message": "MNEMORA API is running."}


@app.get("/api/v1/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "healthy", "application": settings.application_name, "version": settings.application_version}
