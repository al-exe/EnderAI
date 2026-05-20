"""Answer generation + provider router.

Three paths into the LLM, picked by the resolved
``SearchEligibility.route``:

    - ``managed``        → ``settings.ANTHROPIC_API_KEY`` + Claude
    - ``byok:anthropic`` → decrypted user key + Claude
    - ``byok:openai``    → decrypted user key + OpenAI

Both providers stream incrementally; we yield ``TokenEvent`` per
delta and ``DoneEvent`` once usage is finalized. Citations are
emitted before the token stream begins so the frontend can render
source chips while the answer types out."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Literal

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.search.byok import decrypt_api_key
from app.core.search.types import (
    AnswerEvent,
    CitationEvent,
    DoneEvent,
    ErrorEvent,
    SearchHit,
    TokenEvent,
    TokenUsage,
)
from app.core.tiering import SearchEligibility

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are Taskforce Search. Answer the user's question using only the "
    "provided context blocks. Cite sources inline using [doc:anchor] "
    "tokens that match the block headers exactly. If the answer is not "
    "in the context, say so plainly — do not invent facts. Keep "
    "answers concise; prefer two short paragraphs over five long ones."
)


def build_context_block(hits: list[SearchHit]) -> str:
    """Render the retrieved chunks into the {context} slot.

    Each block is prefixed by ``[doc:<source_item_id>:<anchor>]`` so
    citations the model produces map 1:1 back to chunks (and via
    ``source_item_id`` back to the document URL)."""

    parts: list[str] = []
    for hit in hits:
        header = f"[doc:{hit.source_item_id}:{hit.chunk_anchor_id}]"
        parts.append(f"{header}\n{hit.chunk_text}")
    return "\n\n".join(parts)


def build_user_prompt(query: str, hits: list[SearchHit]) -> str:
    if not hits:
        return (
            f"Question: {query}\n\nContext: (no documents matched the query)"
        )
    return f"Question: {query}\n\nContext:\n{build_context_block(hits)}"


async def _stream_claude(
    *,
    api_key: str,
    user_prompt: str,
    billed_to: Literal["managed", "byok:anthropic"],
    model_id: str,
) -> AsyncIterator[AnswerEvent]:
    client = AsyncAnthropic(api_key=api_key)
    async with client.messages.stream(
        model=model_id,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        async for delta in stream.text_stream:
            if delta:
                yield TokenEvent(text=delta)
        final = await stream.get_final_message()
        usage = final.usage
        yield DoneEvent(
            billed_to=billed_to,
            model_id=model_id,
            tokens_consumed=TokenUsage(
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_creation_tokens=(
                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                ),
            ),
        )


async def _stream_openai(
    *,
    api_key: str,
    user_prompt: str,
    model_id: str = "gpt-4o-mini",
) -> AsyncIterator[AnswerEvent]:
    client = AsyncOpenAI(api_key=api_key)
    stream = await client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        stream=True,
        stream_options={"include_usage": True},
    )
    input_tokens = 0
    output_tokens = 0
    async for chunk in stream:
        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield TokenEvent(text=delta.content)
        if chunk.usage:
            input_tokens = chunk.usage.prompt_tokens or 0
            output_tokens = chunk.usage.completion_tokens or 0
    yield DoneEvent(
        billed_to="byok:openai",
        model_id=model_id,
        tokens_consumed=TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    )


async def stream_answer(
    *,
    eligibility: SearchEligibility,
    query: str,
    hits: list[SearchHit],
) -> AsyncIterator[AnswerEvent]:
    """The single entrypoint used by the SSE endpoint. Emits
    citations first, then tokens, then a terminal Done (or Error)."""

    # Citations up front so the UI can render source chips while the
    # answer streams. Frontend ignores citations that arrive mid-stream
    # but we don't need to deal with that here.
    for hit in hits:
        yield CitationEvent(
            source_kind=hit.source_kind,
            source_item_id=hit.source_item_id,
            chunk_anchor_id=hit.chunk_anchor_id,
            title=hit.title,
            url_path=hit.url_path,
            score=hit.score,
        )

    user_prompt = build_user_prompt(query, hits)

    try:
        if eligibility.route == "managed":
            if not settings.ANTHROPIC_API_KEY:
                yield ErrorEvent(
                    code="managed_unavailable",
                    message=(
                        "Managed Claude is not configured on this deployment "
                        "(ANTHROPIC_API_KEY missing)."
                    ),
                )
                return
            async for ev in _stream_claude(
                api_key=settings.ANTHROPIC_API_KEY,
                user_prompt=user_prompt,
                billed_to="managed",
                model_id=settings.SEARCH_ANSWER_MODEL,
            ):
                yield ev
            return

        if eligibility.route == "byok:anthropic":
            cred = next(
                (c for c in eligibility.byok if c.provider == "anthropic"), None
            )
            if cred is None or cred.revoked_at is not None:
                yield ErrorEvent(
                    code="byok_missing",
                    message="No active Anthropic BYOK key on file.",
                )
                return
            api_key = decrypt_api_key(cred.encrypted_api_key)
            async for ev in _stream_claude(
                api_key=api_key,
                user_prompt=user_prompt,
                billed_to="byok:anthropic",
                model_id=settings.SEARCH_ANSWER_MODEL,
            ):
                yield ev
            return

        if eligibility.route == "byok:openai":
            cred = next(
                (c for c in eligibility.byok if c.provider == "openai"), None
            )
            if cred is None or cred.revoked_at is not None:
                yield ErrorEvent(
                    code="byok_missing",
                    message="No active OpenAI BYOK key on file.",
                )
                return
            api_key = decrypt_api_key(cred.encrypted_api_key)
            async for ev in _stream_openai(
                api_key=api_key, user_prompt=user_prompt
            ):
                yield ev
            return

        yield ErrorEvent(
            code="route_unset",
            message="No provider route resolved for this user.",
        )
    except Exception as e:  # pragma: no cover - upstream surface
        log.exception("answer stream failed: %s", e)
        yield ErrorEvent(code="provider_error", message=str(e))
