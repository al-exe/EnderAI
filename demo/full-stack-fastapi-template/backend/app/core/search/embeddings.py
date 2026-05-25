"""Embedding generation for Taskforce Search.

Managed indexing always uses our OpenAI key (``settings.OPENAI_API_KEY``)
so the embedding model stays stable per ``settings.SEARCH_EMBEDDING_MODEL``
(default ``text-embedding-3-small``, 1536d) regardless of which user
or tier triggered the work. We *could* let BYOK users embed against
their own OpenAI key, but that would mean two parallel embedding
spaces in the same index — a non-starter for retrieval consistency.

Per-query embeddings (at search time) also use the managed key for
the same reason. BYOK only affects the *answer* call, not the index."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    # Heavy SDK — kept under TYPE_CHECKING so importing this module at
    # FastAPI startup doesn't pull in the entire openai dependency
    # graph. The real import happens inside ``_client()`` on first use.
    from openai import AsyncOpenAI

log = logging.getLogger(__name__)


class EmbeddingsUnavailableError(RuntimeError):
    """Raised when ``settings.OPENAI_API_KEY`` is missing.

    Search endpoints catch this and return 503 with a clear message;
    indexer catches it and skips the sweep iteration."""


def _client() -> "AsyncOpenAI":
    if not settings.OPENAI_API_KEY:
        raise EmbeddingsUnavailableError(
            "OPENAI_API_KEY is not configured; embedding generation is disabled."
        )
    # Imported lazily — see TYPE_CHECKING block above for why.
    from openai import AsyncOpenAI as _AsyncOpenAI

    return _AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def embed_batch(texts: Iterable[str]) -> list[list[float]]:
    """Return one vector per non-empty input.

    Empty / whitespace-only inputs are dropped at the call site; this
    function trusts its input. We pass everything through in a single
    request so callers can batch up to ~100 chunks per call without
    rate-limit ping-pong."""

    payload = [t for t in texts]
    if not payload:
        return []
    client = _client()
    # The OpenAI Python SDK retries 429 / 5xx with exponential backoff
    # by default — no extra wrapping needed for transient errors.
    resp = await client.embeddings.create(
        model=settings.SEARCH_EMBEDDING_MODEL,
        input=payload,
    )
    return [item.embedding for item in resp.data]


async def embed_one(text: str) -> list[float]:
    """Convenience wrapper for the retrieval path (single query)."""

    vectors = await embed_batch([text])
    if not vectors:
        raise ValueError("Cannot embed empty text.")
    return vectors[0]


async def safe_embed_batch(texts: list[str]) -> list[list[float]] | None:
    """Best-effort variant for the cron-sweep — logs and returns None
    when embeddings are unavailable instead of raising. Keeps the
    sweep loop from crashing the server on a missing API key."""

    try:
        return await embed_batch(texts)
    except EmbeddingsUnavailableError as e:
        log.warning("Embeddings unavailable, skipping sweep batch: %s", e)
        return None
    except Exception as e:  # pragma: no cover - upstream API errors
        log.exception("Embedding batch failed: %s", e)
        return None


async def gather_embeddings(text_groups: list[list[str]]) -> list[list[list[float]]]:
    """Fan a list of text groups out into parallel batch requests.

    Used by the indexer when sweeping more docs than fit comfortably
    in one ``embed_batch`` call. Order is preserved."""

    return list(await asyncio.gather(*(embed_batch(g) for g in text_groups)))
