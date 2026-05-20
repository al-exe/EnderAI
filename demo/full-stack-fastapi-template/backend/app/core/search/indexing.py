"""Indexing pipeline — finds drift, embeds chunks, upserts.

Phase 1 chunks come from V2 documents only. The indexer is connector-
agnostic past the entry point: it accepts any ``Source`` and asks it
for drifted records, then writes them through to
``source_item_embedding`` with the ACL-relevant columns denormalized.

Execution model: a background asyncio task started in
``app.main`` runs ``run_forever()``. Each iteration calls
``sweep_once()`` once for every registered source, sleeps
``settings.SEARCH_INDEX_SWEEP_INTERVAL_SECONDS``, repeats. There is
no Redis / Celery / arq here — when we scale past one web instance,
we wrap ``sweep_once`` with a Postgres advisory lock (Phase 2)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.core.search.connectors import DocumentSource
from app.core.search.connectors.base import Source
from app.core.search.connectors.documents import CURRENT_INDEX_VERSION
from app.core.search.embeddings import (
    EmbeddingsUnavailableError,
    safe_embed_batch,
)
from app.core.search.types import Chunk, SourceItemRecord
from app.models import SourceItemEmbedding, V2Document

log = logging.getLogger(__name__)


@dataclass
class SweepReport:
    processed: int
    chunks_upserted: int
    skipped: int


def chunk_version_hash(chunk_text: str) -> str:
    """Stable per-chunk fingerprint used to short-circuit re-embedding."""

    digest = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
    return digest[:32]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record_to_acl_columns(rec: SourceItemRecord) -> dict[str, object]:
    """Columns we copy onto every chunk row for the ACL filter."""

    return {
        "owner_id": rec.owner_id,
        "organization_id": rec.organization_id,
        "visibility": rec.visibility,
        "is_demo": rec.is_demo,
    }


def _existing_hashes_for_item(
    session: Session, *, source_kind: str, source_item_id: str
) -> dict[str, str]:
    rows = session.exec(
        select(
            SourceItemEmbedding.chunk_anchor_id,
            SourceItemEmbedding.version_hash,
        )
        .where(SourceItemEmbedding.source_kind == source_kind)
        .where(SourceItemEmbedding.source_item_id == source_item_id)
    ).all()
    return {row[0]: row[1] for row in rows}


async def upsert_record(session: Session, rec: SourceItemRecord) -> int:
    """Embed the chunks that have actually changed and upsert. Returns
    the number of chunks (re-)embedded."""

    if not rec.chunks:
        return 0

    existing = _existing_hashes_for_item(
        session, source_kind=rec.source_kind, source_item_id=rec.external_id
    )

    # Decide what to embed.
    to_embed: list[Chunk] = []
    new_hashes: dict[str, str] = {}
    for chunk in rec.chunks:
        h = chunk_version_hash(chunk.text)
        new_hashes[chunk.anchor_id] = h
        if existing.get(chunk.anchor_id) != h:
            to_embed.append(chunk)

    # Anchors that vanished from the source — drop their rows.
    stale_anchors = set(existing.keys()) - set(new_hashes.keys())
    if stale_anchors:
        session.execute(
            delete(SourceItemEmbedding)
            .where(SourceItemEmbedding.source_kind == rec.source_kind)
            .where(SourceItemEmbedding.source_item_id == rec.external_id)
            .where(col(SourceItemEmbedding.chunk_anchor_id).in_(stale_anchors))
        )

    if not to_embed:
        return 0

    vectors = await safe_embed_batch([c.text for c in to_embed])
    if vectors is None:
        # Embeddings unavailable — leave the doc un-indexed; the next
        # sweep will pick it up automatically since last_indexed_at
        # stays in its prior state.
        raise EmbeddingsUnavailableError(
            "Embedding batch failed; deferring sweep."
        )

    acl = _record_to_acl_columns(rec)
    now = _now()
    for chunk, vec in zip(to_embed, vectors, strict=True):
        existing_row = session.exec(
            select(SourceItemEmbedding)
            .where(SourceItemEmbedding.source_kind == rec.source_kind)
            .where(SourceItemEmbedding.source_item_id == rec.external_id)
            .where(SourceItemEmbedding.chunk_anchor_id == chunk.anchor_id)
        ).first()
        if existing_row is None:
            session.add(
                SourceItemEmbedding(
                    source_kind=rec.source_kind,
                    source_item_id=rec.external_id,
                    chunk_anchor_id=chunk.anchor_id,
                    chunk_text=chunk.text,
                    embedding=vec,
                    version_hash=new_hashes[chunk.anchor_id],
                    indexed_at=now,
                    **acl,
                )
            )
        else:
            existing_row.chunk_text = chunk.text
            existing_row.embedding = vec
            existing_row.version_hash = new_hashes[chunk.anchor_id]
            existing_row.indexed_at = now
            for k, v in acl.items():
                setattr(existing_row, k, v)
            session.add(existing_row)

    return len(to_embed)


async def sweep_documents_once(session: Session) -> SweepReport:
    """One iteration of the Documents drift sweep.

    Pulls up to ``settings.SEARCH_INDEX_BATCH_SIZE`` documents whose
    ``last_indexed_at`` is null OR older than ``updated_at`` OR whose
    ``index_version`` doesn't match the current chunking strategy.
    Re-embeds them, then advances both markers."""

    drift_statement = (
        select(V2Document)
        .where(
            (col(V2Document.last_indexed_at).is_(None))
            | (col(V2Document.last_indexed_at) < col(V2Document.updated_at))
            | (col(V2Document.index_version) != CURRENT_INDEX_VERSION)
        )
        .order_by(col(V2Document.updated_at).asc())
        .limit(settings.SEARCH_INDEX_BATCH_SIZE)
    )
    drifted = session.exec(drift_statement).all()
    if not drifted:
        return SweepReport(processed=0, chunks_upserted=0, skipped=0)

    source: Source = DocumentSource()
    chunks_upserted = 0
    skipped = 0
    now = _now()
    for doc in drifted:
        rec = await source.fetch_item(session=session, source_item_id=str(doc.id))
        if rec is None:
            skipped += 1
            continue
        try:
            chunks_upserted += await upsert_record(session, rec)
        except EmbeddingsUnavailableError:
            session.rollback()
            return SweepReport(
                processed=0, chunks_upserted=chunks_upserted, skipped=len(drifted)
            )
        doc.last_indexed_at = now
        doc.index_version = CURRENT_INDEX_VERSION
        session.add(doc)

    session.commit()
    return SweepReport(
        processed=len(drifted), chunks_upserted=chunks_upserted, skipped=skipped
    )


async def run_forever(stop_event: asyncio.Event | None = None) -> None:
    """Long-running sweep loop. Started on FastAPI startup."""

    interval = max(5, settings.SEARCH_INDEX_SWEEP_INTERVAL_SECONDS)
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            with Session(engine) as session:
                report = await sweep_documents_once(session)
            if report.processed:
                log.info(
                    "indexing sweep processed=%s chunks=%s skipped=%s",
                    report.processed,
                    report.chunks_upserted,
                    report.skipped,
                )
        except Exception as e:  # pragma: no cover - defensive
            log.exception("indexing sweep crashed: %s", e)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return


async def backfill_all(*, owner_id: str | None = None) -> SweepReport:
    """One-shot backfill driven by the CLI entrypoint below.

    Sweeps until no more drift exists. Useful right after the alembic
    migration runs so the corpus is searchable on first request."""

    total = SweepReport(processed=0, chunks_upserted=0, skipped=0)
    while True:
        with Session(engine) as session:
            report = await sweep_documents_once(session)
        total = SweepReport(
            processed=total.processed + report.processed,
            chunks_upserted=total.chunks_upserted + report.chunks_upserted,
            skipped=total.skipped + report.skipped,
        )
        if report.processed == 0:
            return total


def _cli_main() -> None:
    """`python -m app.core.search.indexing backfill`."""

    import sys

    if len(sys.argv) < 2 or sys.argv[1] != "backfill":
        print("usage: python -m app.core.search.indexing backfill")  # noqa: T201
        sys.exit(2)
    report = asyncio.run(backfill_all())
    print(  # noqa: T201
        f"backfill done: processed={report.processed} "
        f"chunks={report.chunks_upserted} skipped={report.skipped}"
    )


if __name__ == "__main__":
    _cli_main()
