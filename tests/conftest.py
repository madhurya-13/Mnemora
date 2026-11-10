from pathlib import Path
from importlib import import_module

import pytest
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.database.db import get_db, make_engine
from app.api import chat as chat_api
from app.main import app
import_module("app.models")  # registers every model with Base.metadata


@pytest.fixture(autouse=True)
def temporary_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_url = f"sqlite:///{(tmp_path / 'mnemora_test.sqlite3').as_posix()}"
    engine = make_engine(database_url)
    Base.metadata.create_all(engine)
    state = {"database_url": database_url, "engine": engine, "factory": sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )}

    def override_get_db():
        db = state["factory"]()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    async def do_not_process_background_jobs(_factory=None, **_kwargs):
        return 0

    monkeypatch.setattr(chat_api, "process_pending_jobs", do_not_process_background_jobs)
    yield state
    app.dependency_overrides.pop(get_db, None)
    state["engine"].dispose()
