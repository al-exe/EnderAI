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
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    # Heavy SDK — kept under TYPE_CHECKING so importing this module at
    # FastAPI startup doesn't pull in the entire openai dependency
    # graph. The real import happens inside ``_client()`` on first use.
    from openai import AsyncOpenAI

log = logging.getLogger(__name__)

_embedding_slots = asyncio.Semaphore(max(1, settings.SEARCH_EMBEDDING_MAX_CONCURRENCY))
_circuit_open_until = 0.0
_circuit_reason: str | None = None


class EmbeddingsUnavailableError(RuntimeError):
    """Raised when embedding generation cannot currently serve a request.

    Search endpoints catch this and return 503 with a clear message;
    indexer catches it and skips the sweep iteration."""


def _client() -> AsyncOpenAI:
    if not settings.OPENAI_API_KEY:
        raise EmbeddingsUnavailableError(
            "OPENAI_API_KEY is not configured; embedding generation is disabled."
        )
    # Imported lazily — see TYPE_CHECKING block above for why.
    from openai import AsyncOpenAI as _AsyncOpenAI

    return _AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        max_retries=0,
        timeout=max(1.0, settings.SEARCH_EMBEDDING_TIMEOUT_SECONDS),
    )


def _circuit_error() -> EmbeddingsUnavailableError | None:
    remaining = _circuit_open_until - time.monotonic()
    if remaining <= 0:
        return None
    reason = f" after {_circuit_reason}" if _circuit_reason else ""
    return EmbeddingsUnavailableError(
        "Embedding provider is temporarily unavailable"
        f"{reason}; retry in {max(1, int(remaining))} seconds."
    )


def _open_circuit(error: Exception) -> None:
    global _circuit_open_until, _circuit_reason

    cooldown = max(1.0, settings.SEARCH_EMBEDDING_CIRCUIT_BREAKER_SECONDS)
    _circuit_open_until = time.monotonic() + cooldown
    status_code = getattr(error, "status_code", None)
    _circuit_reason = (
        f"provider HTTP {status_code}" if status_code else "a provider error"
    )


async def embed_batch(texts: Iterable[str]) -> list[list[float]]:
    """Return one vector per non-empty input.

    Empty / whitespace-only inputs are dropped at the call site; this
    function trusts its input. We pass everything through in a single
    request so callers can batch up to ~100 chunks per call without
    rate-limit ping-pong."""

    payload = list(texts)
    if not payload:
        return []
    circuit_error = _circuit_error()
    if circuit_error is not None:
        raise circuit_error

    # Import only when embeddings are used so FastAPI startup stays lightweight.
    from openai import APIError

    async with _embedding_slots:
        # Requests may have queued before another request opened the circuit.
        circuit_error = _circuit_error()
        if circuit_error is not None:
            raise circuit_error

        client = _client()
        try:
            # SDK retries are disabled in _client(). A quota failure must not park
            # the web worker in exponential backoff while more calls queue behind it.
            resp = await client.embeddings.create(
                model=settings.SEARCH_EMBEDDING_MODEL,
                input=payload,
            )
        except APIError as error:
            _open_circuit(error)
            log.warning(
                "Embedding provider failed; circuit opened for %ss: %s",
                max(1.0, settings.SEARCH_EMBEDDING_CIRCUIT_BREAKER_SECONDS),
                error,
            )
            raise EmbeddingsUnavailableError(
                "Embedding provider is temporarily unavailable."
            ) from error
        finally:
            await client.close()

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
