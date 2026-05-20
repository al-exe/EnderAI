"""Shared data shapes for the Search subsystem.

These dataclasses are deliberately not Pydantic / SQLModel — they
travel between modules in-process and would otherwise pull every
connector into the wire-format graph. The Pydantic public shapes live
in ``app.models`` (``SearchEligibilityPublic``, ``SearchQuery``, etc.)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class Chunk:
    """A single indexable unit for one source item."""

    anchor_id: str
    text: str


@dataclass(frozen=True)
class SourceItemRecord:
    """Normalized shape every connector emits.

    For Documents: ``source_kind="documents"``, ``external_id`` is the
    V2Document.id stringified, chunks come from details_markdown_sections
    plus a synthetic "summary" chunk.

    Connectors added in Phase 2+ (Slack, GitHub, Gmail, GDocs) emit the
    same shape — that's the whole point of the abstraction."""

    source_kind: str
    external_id: str
    owner_id: uuid.UUID
    organization_id: uuid.UUID | None
    visibility: Literal["private", "organization"]
    is_demo: bool
    title: str
    url_path: str
    chunks: list[Chunk]
    updated_at: datetime


@dataclass(frozen=True)
class SearchHit:
    """One retrieval result returned to the answer generator."""

    source_kind: str
    source_item_id: str
    chunk_anchor_id: str
    chunk_text: str
    title: str
    url_path: str
    score: float  # cosine similarity, 0..1 (higher = better)


# ---------- SSE event shapes ----------------------------------------


@dataclass(frozen=True)
class TokenEvent:
    kind: Literal["token"] = "token"
    text: str = ""


@dataclass(frozen=True)
class CitationEvent:
    kind: Literal["citation"] = "citation"
    source_kind: str = ""
    source_item_id: str = ""
    chunk_anchor_id: str = ""
    title: str = ""
    url_path: str = ""
    score: float = 0.0


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass(frozen=True)
class DoneEvent:
    kind: Literal["done"] = "done"
    billed_to: Literal["managed", "byok:anthropic", "byok:openai"] = "managed"
    model_id: str = ""
    tokens_consumed: TokenUsage = field(default_factory=TokenUsage)


@dataclass(frozen=True)
class ErrorEvent:
    kind: Literal["error"] = "error"
    code: str = ""
    message: str = ""


AnswerEvent = TokenEvent | CitationEvent | DoneEvent | ErrorEvent
