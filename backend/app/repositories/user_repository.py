"""User identity lookups used by the guest-session dependency."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_guest_session_hash(self, session_hash: str) -> User | None:
        return self.db.scalar(select(User).where(User.guest_session_hash == session_hash))

    def create_guest(self, session_hash: str) -> User:
        user = User(guest_session_hash=session_hash)
        self.db.add(user)
        self.db.flush()
        return user
