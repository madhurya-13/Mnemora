"""OpenAI text embeddings with lazy client creation and bounded content-keyed cache."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import OrderedDict
from functools import lru_cache
from threading import Lock

from app.config import settings

logger = logging.getLogger(__name__)
_cache: OrderedDict[str, list[float]] = OrderedDict()
_cache_lock = Lock()
_CACHE_LIMIT = 512


class EmbeddingConfigurationError(RuntimeError):
    pass


class EmbeddingServiceError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _client():
    if not settings.openai_api_key.strip():
        raise EmbeddingConfigurationError("Add OPENAI_API_KEY to backend/.env to enable semantic memory search.")
    try:
        from openai import AsyncOpenAI
    except ImportError as error:
        raise EmbeddingConfigurationError("Install the OpenAI Python package to enable memory embeddings.") from error
    return AsyncOpenAI(api_key=settings.openai_api_key.strip(), timeout=30.0, max_retries=1)


def _key(text: str, task_type: str) -> str:
    if settings.memory_embedding_provider == "google":
        model = f"google:{settings.gemini_embedding_model}:{settings.gemini_embedding_dimensions}"
    else:
        model = f"openai:{settings.openai_embedding_model}"
    return hashlib.sha256(f"{model}\0{task_type}\0{text}".encode("utf-8")).hexdigest()


def _normalize(vector: list[float]) -> list[float]:
    magnitude = sum(value * value for value in vector) ** 0.5
    if not magnitude:
        raise EmbeddingServiceError("The embedding service returned a zero vector.")
    return [value / magnitude for value in vector]


async def embed_texts(texts: list[str], *, task_type: str = "RETRIEVAL_QUERY") -> list[list[float]]:
    cleaned = [text.strip() for text in texts]
    if not cleaned or any(not text for text in cleaned):
        raise ValueError("Embedding input cannot be empty.")
    keys = [_key(text, task_type) for text in cleaned]
    results: list[list[float] | None] = [None] * len(cleaned)
    missing: dict[str, str] = {}
    with _cache_lock:
        for index, key in enumerate(keys):
            cached = _cache.get(key)
            if cached is not None:
                _cache.move_to_end(key)
                results[index] = cached.copy()
            else:
                missing.setdefault(key, cleaned[index])
    if missing:
        try:
            if settings.memory_embedding_provider == "google":
                from google.genai import types

                from app.services.llm_service import get_genai_client

                response = await get_genai_client().aio.models.embed_content(
                    model=settings.gemini_embedding_model,
                    contents=list(missing.values()),
                    config=types.EmbedContentConfig(
                        task_type=task_type,
                        output_dimensionality=settings.gemini_embedding_dimensions,
                    ),
                )
                vectors = [_normalize(list(item.values)) for item in response.embeddings or []]
            else:
                response = await _client().embeddings.create(
                    model=settings.openai_embedding_model,
                    input=list(missing.values()),
                    encoding_format="float",
                )
                vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
            if len(vectors) != len(missing) or any(not vector for vector in vectors):
                raise EmbeddingServiceError("The embedding service returned an invalid vector batch.")
        except (EmbeddingConfigurationError, EmbeddingServiceError):
            raise
        except Exception as error:
            logger.error("Embedding provider failed (%s).", type(error).__name__)
            raise EmbeddingServiceError("The embedding provider could not create a vector.") from error
        vectors_by_key = dict(zip(missing.keys(), vectors, strict=True))
        with _cache_lock:
            for key, vector in vectors_by_key.items():
                _cache[key] = list(vector)
                _cache.move_to_end(key)
                while len(_cache) > _CACHE_LIMIT:
                    _cache.popitem(last=False)
        results = [results[index] if results[index] is not None else vectors_by_key[keys[index]].copy() for index in range(len(cleaned))]
    return [vector for vector in results if vector is not None]


async def embed_text(text: str, *, task_type: str = "RETRIEVAL_QUERY") -> list[float]:
    return (await embed_texts([text], task_type=task_type))[0]


async def embed_document(text: str) -> list[float]:
    if settings.memory_embedding_provider == "google":
        return await embed_text(text, task_type="RETRIEVAL_DOCUMENT")
    return await embed_text(text)


def clear_embedding_cache() -> None:
    with _cache_lock:
        _cache.clear()
    _client.cache_clear()
