"""Offline evolution orchestrator (T0).

Fans out doc-synthesis (T1 auto-create; T2 auto-update) and profile compounding
after a material session is summarized. Runs only in the background sweeper or
a CLI entrypoint — never on the observe request path.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import cast, String
from sqlmodel import Session, col, select

from app.core.agents.compounding import compound_specialists
from app.core.config import settings
from app.core.db import engine
from app.core.taskforce.evolution_doc_synthesis import synthesize_documents
from app.core.taskforce.evolution_gate import can_auto_evolve
from app.core.taskforce.evolution_summary import EVOLUTION_SUMMARY_KEY
from app.core.taskforce.summarizer import SummarizerResult
from app.models import TaskforceSessionArchive, get_datetime_utc

log = logging.getLogger(__name__)

EVOLUTION_PENDING_KEY = "evolution_pending"
EVOLUTION_PROCESSED_AT_KEY = "evolution_processed_at"


@dataclass(frozen=True)
class EvolutionResult:
    skipped: bool
    skip_reason: str | None = None
    docs_created: list[uuid.UUID] = field(default_factory=list)
    docs_updated: list[uuid.UUID] = field(default_factory=list)
    compounding: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class EvolutionSweepReport:
    processed: int
    skipped: int


def mark_session_for_evolution(
    archive: TaskforceSessionArchive,
    *,
    summary: SummarizerResult | None = None,
    visibility: str | None = None,
) -> None:
    """Flag a summarized material session for the offline sweeper."""

    metadata = dict(archive.source_metadata or {})
    metadata[EVOLUTION_PENDING_KEY] = True
    metadata.pop(EVOLUTION_PROCESSED_AT_KEY, None)
    if visibility is not None:
        metadata["visibility"] = visibility
    if summary is not None:
        metadata[EVOLUTION_SUMMARY_KEY] = {
            "summary_points": list(summary.summary_points),
            "details_sections": list(summary.details_sections),
            "decisions": list(summary.decisions),
            "outcome": summary.outcome,
            "materiality_score": summary.materiality_score,
        }
    archive.source_metadata = metadata
    archive.updated_at = get_datetime_utc()


def _run_doc_synthesis(
    session: Session,
    *,
    archive: TaskforceSessionArchive,
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Auto-create / auto-update Library docs from the session (T1/T2)."""

    return synthesize_documents(session, archive=archive)


def evolve_session(
    session: Session,
    archive: TaskforceSessionArchive,
) -> EvolutionResult:
    """Run offline evolution for one summarized session archive row."""

    eligibility = can_auto_evolve(session, organization_id=archive.organization_id)
    if not eligibility.allowed:
        return EvolutionResult(
            skipped=True,
            skip_reason=eligibility.reason or "blocked",
        )

    docs_created, docs_updated = _run_doc_synthesis(session, archive=archive)
    compounding = compound_specialists(
        session,
        organization_id=archive.organization_id,
        dry_run=False,
    )

    metadata = dict(archive.source_metadata or {})
    metadata[EVOLUTION_PENDING_KEY] = False
    metadata[EVOLUTION_PROCESSED_AT_KEY] = datetime.now(timezone.utc).isoformat()
    archive.source_metadata = metadata
    archive.updated_at = get_datetime_utc()
    session.add(archive)

    return EvolutionResult(
        skipped=False,
        docs_created=docs_created,
        docs_updated=docs_updated,
        compounding=compounding,
    )


def _pending_archives_statement(limit: int):
    pending = cast(
        TaskforceSessionArchive.source_metadata[EVOLUTION_PENDING_KEY].astext,  # type: ignore[index]
        String,
    )
    return (
        select(TaskforceSessionArchive)
        .where(pending == "true")
        .order_by(col(TaskforceSessionArchive.updated_at).asc())
        .limit(limit)
    )


def sweep_pending_once(session: Session) -> EvolutionSweepReport:
    """Process a batch of archives flagged by observe."""

    if not settings.TF_SELF_EVOLVE:
        return EvolutionSweepReport(processed=0, skipped=0)

    archives = list(
        session.exec(
            _pending_archives_statement(settings.EVOLUTION_SWEEP_BATCH_SIZE)
        ).all()
    )
    if not archives:
        return EvolutionSweepReport(processed=0, skipped=0)

    processed = 0
    skipped = 0
    for archive in archives:
        result = evolve_session(session, archive)
        if result.skipped:
            skipped += 1
            metadata = dict(archive.source_metadata or {})
            metadata[EVOLUTION_PENDING_KEY] = False
            metadata[EVOLUTION_PROCESSED_AT_KEY] = datetime.now(
                timezone.utc
            ).isoformat()
            metadata["evolution_skip_reason"] = result.skip_reason
            archive.source_metadata = metadata
            archive.updated_at = get_datetime_utc()
            session.add(archive)
        else:
            processed += 1

    session.commit()
    return EvolutionSweepReport(processed=processed, skipped=skipped)


async def run_forever(stop_event: asyncio.Event | None = None) -> None:
    """Background sweeper started from FastAPI lifespan when enabled."""

    interval = max(10, settings.EVOLUTION_SWEEP_INTERVAL_SECONDS)
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            with Session(engine) as session:
                report = sweep_pending_once(session)
            if report.processed or report.skipped:
                log.info(
                    "evolution sweep processed=%s skipped=%s",
                    report.processed,
                    report.skipped,
                )
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("evolution sweep crashed: %s", exc)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return


def sweep_pending_cli() -> EvolutionSweepReport:
    """One-shot sweep for local ops / tests."""

    with Session(engine) as session:
        report = sweep_pending_once(session)
    return report
