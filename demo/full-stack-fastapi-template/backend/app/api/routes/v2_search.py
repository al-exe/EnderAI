"""Taskforce V2 Search — the chat-style retrieval endpoint.

Two routes:

* ``GET  /v2/search/eligibility`` — drives the frontend's gate UI.
* ``POST /v2/search``             — Server-Sent Events stream of
  ``token`` / ``citation`` / ``done`` / ``error`` events.

The SSE channel is deliberately outside the openapi-ts auto-generated
client; the frontend talks to it through ``src/lib/searchStream.ts``
which uses ``fetchEventSource``. Keeping it off the OpenAPI surface
means we don't have to teach openapi-ts about streaming.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.api.deps import CurrentUser, SessionDep
from app.core.metrics.events import record_search_usage
from app.core.search import indexing as search_indexing
from app.core.search.answer import stream_answer
from app.core.search.embeddings import EmbeddingsUnavailableError
from app.core.search.retrieval import retrieve
from app.core.search.types import (
    AnswerEvent,
    CitationEvent,
    DoneEvent,
    ErrorEvent,
    SearchHit,
    TokenEvent,
)
from app.core.tiering import SearchEligibility, can_use_search, public_tier
from app.models import (
    ByokCredential,
    ByokCredentialPublic,
    SearchEligibilityPublic,
    SearchQuery,
    TaskforceUsagePayload,
    User,
    V2Document,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/search", tags=["v2-search"])


# ---- helpers --------------------------------------------------------


def _byok_for(session: Session, user: User) -> list[ByokCredential]:
    return list(
        session.exec(
            select(ByokCredential).where(ByokCredential.user_id == user.id)
        ).all()
    )


def _byok_public(creds: list[ByokCredential]) -> list[ByokCredentialPublic]:
    return [
        ByokCredentialPublic(
            provider=c.provider,
            key_fingerprint=c.key_fingerprint,
            created_at=c.created_at,
            last_validated_at=c.last_validated_at,
            revoked_at=c.revoked_at,
        )
        for c in creds
    ]


def _eligibility_to_public(
    eligibility: SearchEligibility, byok: list[ByokCredential]
) -> SearchEligibilityPublic:
    return SearchEligibilityPublic(
        tier=public_tier(eligibility.tier),
        allowed=eligibility.allowed,
        route=eligibility.route,
        reason=eligibility.reason,
        byok=_byok_public(byok),
    )


def _format_sse(event: AnswerEvent) -> str:
    """Encode an AnswerEvent as a single SSE message.

    Format:
        event: <kind>\\n
        data: <json>\\n\\n
    """

    if isinstance(event, TokenEvent):
        payload: dict[str, Any] = {"text": event.text}
        kind = "token"
    elif isinstance(event, CitationEvent):
        payload = {
            "source_kind": event.source_kind,
            "source_item_id": event.source_item_id,
            "chunk_anchor_id": event.chunk_anchor_id,
            "title": event.title,
            "url_path": event.url_path,
            "score": event.score,
        }
        kind = "citation"
    elif isinstance(event, DoneEvent):
        payload = {
            "billed_to": event.billed_to,
            "model_id": event.model_id,
            "tokens_consumed": asdict(event.tokens_consumed),
        }
        kind = "done"
    elif isinstance(event, ErrorEvent):
        payload = {"code": event.code, "message": event.message}
        kind = "error"
    else:  # pragma: no cover - exhaustiveness
        payload = {"text": str(event)}
        kind = "token"
    return f"event: {kind}\ndata: {json.dumps(payload)}\n\n"


# ---- /v2/search/eligibility ----------------------------------------


@router.get("/eligibility", response_model=SearchEligibilityPublic)
def read_search_eligibility(
    *,
    session: SessionDep,
    current_user: CurrentUser,
) -> SearchEligibilityPublic:
    byok = _byok_for(session, current_user)
    eligibility = can_use_search(current_user, byok)
    return _eligibility_to_public(eligibility, byok)


# ---- POST /v2/search -----------------------------------------------


@router.post("")
async def stream_search(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: SearchQuery,
) -> StreamingResponse:
    byok = _byok_for(session, current_user)
    eligibility = can_use_search(current_user, byok)
    if not eligibility.allowed:
        if eligibility.reason == "upgrade_required":
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Search requires a Pro or Max subscription.",
            )
        if eligibility.reason == "byok_required":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Pro tier requires a BYOK Anthropic or OpenAI key. "
                    "Add one in Settings → Search."
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Search is unavailable for this account.",
        )

    # Run retrieval before opening the SSE stream so we can return a
    # clean 5xx if embeddings are down; once we yield the first byte
    # the response code is already committed.
    try:
        hits = await retrieve(
            session=session,
            actor=current_user,
            query=body.query,
            top_k=body.top_k,
            demo=body.demo,
        )
    except EmbeddingsUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    async def event_source() -> AsyncIterator[str]:
        last_event: AnswerEvent | None = None
        async for event in stream_answer(
            eligibility=eligibility, query=body.query, hits=hits
        ):
            last_event = event
            yield _format_sse(event)
        # Record usage AFTER the stream completes. Done in a fresh
        # session view so we don't tangle with the request session's
        # autocommit semantics during the long-lived stream.
        if isinstance(last_event, DoneEvent):
            try:
                _record_done(session, current_user, last_event, hits, body.demo)
                session.commit()
            except Exception as e:  # pragma: no cover - metrics is non-critical
                log.exception("failed to record search usage: %s", e)
                session.rollback()

    headers = {
        # SSE conventions: no buffering, keep the connection open.
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        event_source(), media_type="text/event-stream", headers=headers
    )


def _record_done(
    session: Session,
    user: User,
    done: DoneEvent,
    hits: list[SearchHit],
    demo: bool,
) -> None:
    """Attribute the search answer's token spend.

    Top hit (if any) is recorded as the document — that gives the
    per-document metrics page a useful "documents that drove the most
    Search spend" view down the road. Empty hits → user-level event."""

    document: V2Document | None = None
    if hits:
        try:
            document = session.exec(
                select(V2Document).where(
                    V2Document.id == uuid.UUID(hits[0].source_item_id)
                )
            ).first()
        except (ValueError, TypeError):
            document = None

    usage = TaskforceUsagePayload(
        model_id=done.model_id or "unknown",
        input_tokens=done.tokens_consumed.input_tokens,
        output_tokens=done.tokens_consumed.output_tokens,
        cache_read_input_tokens=done.tokens_consumed.cache_read_tokens,
        cache_creation_input_tokens=done.tokens_consumed.cache_creation_tokens,
    )
    record_search_usage(
        session,
        user=user,
        usage=usage,
        document=document,
        is_demo=demo,
        billed_to=done.billed_to,
    )


# ---- admin backfill (debug only) -----------------------------------


@router.post("/admin/backfill")
async def admin_backfill(
    *,
    current_user: CurrentUser,
) -> dict[str, int]:
    """One-shot trigger for the embedding backfill. Superusers only."""

    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Backfill requires superuser access.",
        )
    report = await search_indexing.backfill_all()
    return {
        "processed": report.processed,
        "chunks_upserted": report.chunks_upserted,
        "skipped": report.skipped,
    }
