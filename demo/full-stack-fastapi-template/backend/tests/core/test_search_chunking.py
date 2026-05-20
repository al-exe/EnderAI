"""DocumentSource chunking — pure unit tests, no DB."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.core.search.connectors.documents import (
    MAX_CHUNK_CHARS,
    build_chunks_from_document,
)
from app.models import V2Document


def _doc(
    *,
    summary_human: str = "",
    summary_ai: str = "",
    sections: list[dict[str, str]] | None = None,
) -> V2Document:
    return V2Document(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        title="Doc",
        human_summary=summary_human,
        ai_generated_summary=summary_ai,
        details_markdown_sections=sections or [],  # type: ignore[arg-type]
        updated_at=datetime.now(timezone.utc),
    )


def test_no_summary_no_sections_yields_no_chunks() -> None:
    assert build_chunks_from_document(_doc()) == []


def test_summary_chunk_built_from_concatenation() -> None:
    doc = _doc(summary_human="A claim.", summary_ai="An ai claim.")
    chunks = build_chunks_from_document(doc)
    assert len(chunks) == 1
    assert chunks[0].anchor_id == "summary"
    assert "A claim." in chunks[0].text
    assert "An ai claim." in chunks[0].text


def test_empty_summary_strings_skipped() -> None:
    doc = _doc(summary_human="   ", summary_ai="actual text")
    chunks = build_chunks_from_document(doc)
    assert chunks[0].text == "actual text"


def test_details_section_becomes_chunk_keyed_by_anchor() -> None:
    doc = _doc(
        sections=[
            {"anchor_id": "findings", "markdown": "the finding"},
            {"anchor_id": "outcome", "markdown": "the outcome"},
        ],
    )
    chunks = build_chunks_from_document(doc)
    anchors = [c.anchor_id for c in chunks]
    assert anchors == ["findings", "outcome"]


def test_blank_section_is_skipped() -> None:
    doc = _doc(
        sections=[
            {"anchor_id": "findings", "markdown": ""},
            {"anchor_id": "outcome", "markdown": "real content"},
        ],
    )
    chunks = build_chunks_from_document(doc)
    assert [c.anchor_id for c in chunks] == ["outcome"]


def test_long_section_split_into_numbered_subchunks() -> None:
    paragraphs = ["x" * 800] * 5  # ~4000 chars total, well over MAX_CHUNK_CHARS
    big = "\n\n".join(paragraphs)
    doc = _doc(sections=[{"anchor_id": "wall-of-text", "markdown": big}])
    chunks = build_chunks_from_document(doc)
    assert len(chunks) > 1
    assert all(c.anchor_id.startswith("wall-of-text") for c in chunks)
    assert all("#" in c.anchor_id for c in chunks)
    # Every emitted chunk respects the size cap so the embedding call
    # never blows past the model's input limit.
    assert all(len(c.text) <= MAX_CHUNK_CHARS + 200 for c in chunks)
