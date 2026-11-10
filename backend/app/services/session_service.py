"""Opaque, HttpOnly guest sessions with only hashes persisted in SQLite."""

import hashlib
import secrets

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database.db import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_current_user(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> User:
    """Resolve the opaque guest cookie; the client never chooses an owner ID."""
    token = request.cookies.get(settings.guest_session_cookie)
    repo = UserRepository(db)
    user = repo.get_by_guest_session_hash(_token_hash(token)) if token else None
    if user is not None:
        return user

    token = secrets.token_urlsafe(32)
    user = repo.create_guest(_token_hash(token))
    db.commit()
    response.set_cookie(
        key=settings.guest_session_cookie,
        value=token,
        max_age=settings.guest_session_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return user
