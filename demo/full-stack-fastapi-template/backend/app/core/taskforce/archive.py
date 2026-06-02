"""Taskforce session archive ingestion for the Ledger detail surface."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from typing import Any

from sqlmodel import Session, select

from app.models import TaskforceObserveRequest, TaskforceSessionArchive, User

_MAX_EVENT_TEXT = 4000
_MAX_TITLE = 255


def upsert_session_archive_from_observe(
    session: Session,
    *,
    actor: User,
    request: TaskforceObserveRequest,
    demo: bool,
    document_id: uuid.UUID | None = None,
) -> TaskforceSessionArchive | None:
    """Persist a best-effort session archive from an observe payload.

    The observe endpoint receives richer session context than the existing
    metrics ledger stores. This read model preserves that context so Ledger can
    render a transcript/detail view while the old metrics grouping remains a
    compatibility fallback.
    """

    if not request.session_id:
        return None

    now = _now()
    archive = session.exec(
        select(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.organization_id == actor.organization_id)
        .where(TaskforceSessionArchive.is_demo == demo)
        .where(TaskforceSessionArchive.session_id == request.session_id)
    ).first()
    if archive is None:
        archive = TaskforceSessionArchive(
            session_id=request.session_id,
            actor_id=actor.id,
            organization_id=actor.organization_id,
            is_demo=demo,
            imported_at=now,
            created_at=now,
        )

    started_at = _started_at(now, request.duration_ms)
    events = _normalized_events(request, now=now)
    raw_transcript = [
        {"role": turn.role, "content": turn.content[:_MAX_EVENT_TEXT]}
        for turn in request.transcript
    ]
    referenced_ids = _referenced_document_ids(
        existing=archive.referenced_document_ids,
        request=request,
        document_id=document_id,
    )

    archive.actor_id = actor.id
    archive.organization_id = actor.organization_id
    archive.client = request.client or archive.client
    archive.specialist_slug = request.specialist_slug or archive.specialist_slug
    archive.harness_label = request.client or archive.harness_label
    archive.model_id = (
        request.harness.model_id if request.harness is not None else archive.model_id
    )
    archive.cwd = request.cwd or archive.cwd
    archive.repo = _repo_from_cwd(request.cwd) or archive.repo
    archive.branch = request.branch or archive.branch
    archive.title = _title_from_request(request) or archive.title
    archive.started_at = _earliest(archive.started_at, started_at)
    archive.ended_at = now if request.kind == "final" else archive.ended_at
    archive.duration_ms = max(archive.duration_ms or 0, request.duration_ms or 0)
    archive.message_count = max(archive.message_count or 0, len(request.transcript))
    archive.command_count = max(
        archive.command_count or 0,
        len(request.commands_run),
    )
    archive.edit_count = max(archive.edit_count or 0, len(request.files_touched))
    if request.harness is not None:
        archive.input_tokens = request.harness.total_input_tokens
        archive.output_tokens = request.harness.total_output_tokens
        archive.cache_read_tokens = request.harness.total_cache_read_tokens
        archive.cache_write_tokens = request.harness.total_cache_write_tokens
    if events:
        archive.transcript_events = events
    if raw_transcript:
        archive.raw_transcript = raw_transcript
    archive.referenced_document_ids = referenced_ids
    archive.source_metadata = {
        **(archive.source_metadata or {}),
        "kind": request.kind,
        "checkpoint_index": request.checkpoint_index,
        "outcome": request.outcome,
        "summary_points_count": len(request.summary_points),
        "details_sections_count": len(request.details_sections),
        "decisions_count": len(request.decisions),
        "has_structured_payload": bool(
            request.summary_points
            or request.details_sections
            or request.decisions
            or request.outcome
        ),
    }
    archive.updated_at = now
    session.add(archive)
    return archive


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _started_at(now: datetime, duration_ms: int) -> datetime:
    if duration_ms <= 0:
        return now
    return now - timedelta(milliseconds=duration_ms)


def _earliest(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _repo_from_cwd(cwd: str | None) -> str | None:
    if not cwd:
        return None
    try:
        return PurePath(cwd).name[:255] or None
    except ValueError:
        return None


def _title_from_request(request: TaskforceObserveRequest) -> str | None:
    title = request.summary_points[0] if request.summary_points else request.prompt
    normalized = " ".join((title or "").split())
    return normalized[:_MAX_TITLE] or None


def _referenced_document_ids(
    *,
    existing: list[str],
    request: TaskforceObserveRequest,
    document_id: uuid.UUID | None,
) -> list[str]:
    ids: list[str] = list(existing or [])
    for value in (request.active_document_id, document_id):
        if value is not None:
            ids.append(str(value))
    deduped: list[str] = []
    seen: set[str] = set()
    for value in ids:
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped[:50]


def _normalized_events(
    request: TaskforceObserveRequest,
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for turn in request.transcript:
        role = (turn.role or "").lower()
        kind = "prompt" if role in {"user", "human"} else "reply"
        events.append(
            {
                "kind": kind,
                "occurred_at": now.isoformat(),
                "role": turn.role,
                "who": "@user" if kind == "prompt" else "@agent",
                "text": turn.content[:_MAX_EVENT_TEXT],
            }
        )

    if request.prompt and not any(event["kind"] == "prompt" for event in events):
        events.insert(
            0,
            {
                "kind": "prompt",
                "occurred_at": now.isoformat(),
                "role": "user",
                "who": "@user",
                "text": request.prompt[:_MAX_EVENT_TEXT],
            },
        )

    for command in request.commands_run:
        events.append(
            {
                "kind": "command",
                "occurred_at": now.isoformat(),
                "cmd": command.cmd[:2000],
                "exit_code": command.exit_code,
                "repo": _repo_from_cwd(request.cwd),
            }
        )

    for file_name in request.files_touched:
        events.append(
            {
                "kind": "edit",
                "occurred_at": now.isoformat(),
                "file": file_name[:1024],
                "note": (request.diff_summary or "")[:_MAX_EVENT_TEXT] or None,
            }
        )

    if request.kind == "final":
        note = "Session ended"
        if request.outcome:
            note = f"{note} · {request.outcome}"
        events.append(
            {
                "kind": "note",
                "occurred_at": now.isoformat(),
                "text": note,
            }
        )

    return events[:200]
