"""Persistent Chroma vector index; all operations accept explicit user-scoped IDs."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from app.config import settings

logger = logging.getLogger(__name__)
COLLECTION_NAME = "mnemora_user_memories"


class VectorStoreError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _collection(path: str):
    try:
        import chromadb

        persistent_path = Path(path).expanduser().resolve()
        persistent_path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(persistent_path))
        return client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine", "description": "MNEMORA user-owned approved memories"},
            embedding_function=None,
        )
    except Exception as error:
        logger.error("Could not open persistent Chroma collection (%s).", type(error).__name__)
        raise VectorStoreError("The persistent memory index is unavailable.") from error


def _get(path: str | None = None):
    return _collection(str(Path(path or settings.chroma_db_path).expanduser().resolve()))


def upsert_memory(memory: Any, embedding: list[float], path: str | None = None) -> None:
    try:
        collection = _get(path)
        collection.upsert(
            ids=[str(memory.memory_id)],
            embeddings=[embedding],
            documents=[memory.content],
            metadatas=[{
                "user_id": str(memory.user_id),
                "category": memory.category,
                "importance": float(memory.importance),
                "confidence": float(memory.confidence),
                "memory_type": memory.memory_type,
                "source_conversation_id": str(memory.source_conversation_id or ""),
                "created_at": memory.created_at.isoformat(),
                "updated_at": memory.updated_at.isoformat(),
            }],
        )
    except VectorStoreError:
        raise
    except Exception as error:
        logger.error("Chroma upsert failed (%s).", type(error).__name__)
        raise VectorStoreError("The memory vector could not be stored.") from error


def delete_memory(memory_id: UUID, path: str | None = None) -> None:
    try:
        _get(path).delete(ids=[str(memory_id)])
    except Exception as error:
        logger.error("Chroma delete failed (%s).", type(error).__name__)
        raise VectorStoreError("The memory vector could not be deleted.") from error


def query_user(
    user_id: UUID,
    embedding: list[float],
    *,
    limit: int,
    category: str | None = None,
    path: str | None = None,
) -> list[dict[str, Any]]:
    try:
        where: dict[str, Any] = {"user_id": str(user_id)}
        if category:
            where = {"$and": [{"user_id": str(user_id)}, {"category": category}]}
        result = _get(path).query(
            query_embeddings=[embedding],
            n_results=limit,
            where=where,
            include=["metadatas", "documents", "distances"],
        )
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        return [
            {"id": ids[index], "distance": float(distances[index]), "document": documents[index], "metadata": metadatas[index]}
            for index in range(len(ids))
        ]
    except Exception as error:
        logger.error("Chroma query failed (%s).", type(error).__name__)
        raise VectorStoreError("The memory search index is unavailable.") from error


def count_vectors(path: str | None = None) -> int:
    try:
        return int(_get(path).count())
    except Exception as error:
        logger.error("Chroma count failed (%s).", type(error).__name__)
        raise VectorStoreError("The memory index statistics are unavailable.") from error


def runtime_available(path: str | None = None) -> bool:
    """Probe the runtime each time so a transient import failure can recover."""
    try:
        _get(path)
        return True
    except VectorStoreError:
        return False


def clear_collection_cache() -> None:
    _collection.cache_clear()
