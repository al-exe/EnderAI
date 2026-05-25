"""Documents connector — the only real Source in Phase 1.

Reads from ``v2_document`` and emits one ``SourceItemRecord`` per
document with chunks built from ``details_markdown_sections`` plus a
synthetic ``summary`` chunk. Chunking rule:

    - One chunk per details_markdown_sections[i], keyed by its
      ``anchor_id``. That anchor_id is the same one Summary segments
      cite via ``evidence_anchor_id`` — so retrieved chunks can be
      rendered with their original anchor link.
    - One synthetic chunk with anchor_id = "summary" built from
      ``f"{human_summary}\\n\\n{ai_generated_summary}"``.
    - Skip empty chunks. Skip chunks longer than ``MAX_CHUNK_CHARS``
      after a paragraph split (very long sections get fanned out into
      multiple "<anchor>#N" chunks).

The connector does NOT enforce ACLs — that happens at retrieval time
(``app/core/search/retrieval.py``). Here we just emit the records as
they appear in the DB; the denormalized ``owner_id`` / ``visibility``
/ ``organization_id`` we copy onto each ``source_item_embedding`` row
is what the retrieval filter then uses."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar, Iterable, Literal, cast

from sqlmodel import Session, col, select

from app.core.search.types import Chunk, SourceItemRecord
from app.models import V2Document

MAX_CHUNK_CHARS = 2000
# Bump this string whenever the chunking strategy changes. The cron
# sweep treats every row whose ``index_version`` != CURRENT as drift,
# which transparently re-embeds the whole corpus.
CURRENT_INDEX_VERSION = "documents.v1"


def _normalize_visibility(raw: str) -> Literal["private", "organization"]:
    return "organization" if raw == "organization" else "private"


def _summary_chunk(doc: V2Document) -> Chunk | None:
    parts = [s for s in (doc.human_summary, doc.ai_generated_summary) if s and s.strip()]
    if not parts:
        return None
    return Chunk(anchor_id="summary", text="\n\n".join(parts).strip())


def _details_chunks(doc: V2Document) -> list[Chunk]:
    chunks: list[Chunk] = []
    for raw in doc.details_markdown_sections or []:
        anchor = str(raw.get("anchor_id") or "").strip()
        text = str(raw.get("markdown") or "").strip()
        if not anchor or not text:
            continue
        if len(text) <= MAX_CHUNK_CHARS:
            chunks.append(Chunk(anchor_id=anchor, text=text))
            continue
        # Long section: split on blank lines, group into <=MAX_CHUNK_CHARS
        # buckets, emit as <anchor>#1, <anchor>#2, ...
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        bucket: list[str] = []
        bucket_len = 0
        suffix = 1
        for p in paragraphs:
            if bucket_len + len(p) + 2 > MAX_CHUNK_CHARS and bucket:
                chunks.append(
                    Chunk(anchor_id=f"{anchor}#{suffix}", text="\n\n".join(bucket))
                )
                suffix += 1
                bucket = []
                bucket_len = 0
            bucket.append(p)
            bucket_len += len(p) + 2
        if bucket:
            chunks.append(
                Chunk(anchor_id=f"{anchor}#{suffix}", text="\n\n".join(bucket))
            )
    return chunks


def build_chunks_from_document(doc: V2Document) -> list[Chunk]:
    """Pure function — what the indexer would store for ``doc``."""

    out: list[Chunk] = []
    summary = _summary_chunk(doc)
    if summary is not None:
        out.append(summary)
    out.extend(_details_chunks(doc))
    return out


def document_to_record(doc: V2Document) -> SourceItemRecord:
    """Map a V2Document row to the generic SourceItemRecord shape."""

    return SourceItemRecord(
        source_kind=DocumentSource.kind,
        external_id=str(doc.id),
        owner_id=doc.owner_id,
        organization_id=doc.organization_id,
        visibility=_normalize_visibility(doc.visibility),
        is_demo=doc.is_demo,
        title=doc.title,
        url_path=f"/v2/library/{doc.id}",
        chunks=build_chunks_from_document(doc),
        updated_at=cast(datetime, doc.updated_at),
    )


class DocumentSource:
    """V2 documents → indexable records."""

    kind: ClassVar[str] = "documents"

    async def list_items(
        self,
        *,
        session: Session,
        owner_id: uuid.UUID | None = None,
        since: datetime | None = None,
        limit: int = 50,
    ) -> Iterable[SourceItemRecord]:
        """Yield documents that have drifted since ``since``.

        Note: this method intentionally ignores ACL. The indexing
        pipeline runs as a system actor that needs to embed every
        document the user can ever access from any vantage point.
        Per-actor ACL is enforced in ``retrieval.py`` instead."""

        statement = select(V2Document)
        if owner_id is not None:
            statement = statement.where(V2Document.owner_id == owner_id)
        if since is not None:
            statement = statement.where(V2Document.updated_at > since)
        statement = statement.order_by(col(V2Document.updated_at).asc()).limit(limit)
        rows = session.exec(statement).all()
        return [document_to_record(doc) for doc in rows]

    async def fetch_item(
        self,
        *,
        session: Session,
        source_item_id: str,
    ) -> SourceItemRecord | None:
        try:
            doc_uuid = uuid.UUID(source_item_id)
        except ValueError:
            return None
        doc = session.exec(
            select(V2Document).where(V2Document.id == doc_uuid)
        ).first()
        if doc is None:
            return None
        return document_to_record(doc)

    async def handle_event(
        self,
        *,
        session: Session,
        payload: dict[str, Any],
    ) -> Iterable[SourceItemRecord]:
        """Documents indexing is driven by the cron sweep, not webhooks.
        This method exists to satisfy the protocol; calling it is a
        no-op."""

        return []
