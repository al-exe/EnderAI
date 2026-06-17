"""Active-sessions roster (TF-225) and Sessions agent roster (TF-227).

Gives each session a glanceable view of what its sibling sessions — other
currently-open Claude Code instances for the same actor — are doing right
now. Several consumers share the underlying row query in this module:

- ``POST /v2/taskforce/discover`` (hook-driven, every prompt): also records
  a heartbeat for the calling session via :func:`touch_session_heartbeat`,
  then calls :func:`get_active_sessions`.
- ``GET /v2/taskforce/active-sessions`` (frontend presence rail): read-only,
  calls :func:`get_active_sessions`.
- ``GET /v2/taskforce/fleet`` and friends (Sessions control panel, TF-227):
  call :func:`active_sessions_for_actor`, which returns the richer
  ``TaskforceFleetAgentPublic`` shape.

See ``docs/planning/taskforce-active-sessions-roster.md`` and
``docs/planning/taskforce-fleet-tab.md`` for the design.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc
from sqlmodel import Session, col, select

from app.core.taskforce.archive import _now, _repo_from_cwd
from app.core.taskforce.conversation_summary import summarize_opening_prompt
from app.core.taskforce.fleet_sessions import (
    get_or_create_default_fleet_session,
    history_fleet_session_for_actor,
    resurrect_archive_from_history,
)
from app.core.taskforce.session_provenance import merge_session_client
from app.core.taskforce.session_activity import record_activity_prompt
from app.models import (
    AgentSpecialist,
    TaskforceActiveSession,
    TaskforceDiscoverRequest,
    TaskforceFleetAgentPublic,
    TaskforceSessionArchive,
    User,
    V2Document,
)

# Backstop window: a session that hasn't heartbeat in this long is treated as
# abandoned/crashed even if it never got a clean ``ended_at``. Properly-ended
# sessions are excluded outright regardless of this window.
MAX_AGE = timedelta(hours=8)

# Bounds the roster size regardless of how many sessions a user accumulates.
ROSTER_LIMIT = 5

# Sessions reports a server-derived state so clients do not duplicate freshness
# heuristics. Waiting and paused remain reserved until ingestion captures them.
# An agent stays live (running/waiting) until it has been silent for this long,
# then flips to ``idle`` — matched to MAX_AGE so a session is "active" for its
# whole live window and only goes inactive once it ages out of the roster.
FLEET_RUNNING_WINDOW = timedelta(hours=8)

# History keeps more receipts than the live roster cap.
HISTORY_ROSTER_LIMIT = 50


def touch_session_heartbeat(
    session: Session,
    *,
    actor: User,
    request: TaskforceDiscoverRequest,
    demo: bool,
) -> TaskforceSessionArchive | None:
    """Record "this session is still alive" on every ``/discover`` call.

    Creates a minimal archive row if one doesn't exist yet (e.g. the first
    prompt of a session, before any checkpoint has fired) so the session
    shows up in siblings' rosters immediately, with ``active_document_id``
    left null until the first observe.
    """

    if not request.session_id:
        return None

    return register_session_heartbeat(
        session,
        actor=actor,
        session_id=request.session_id,
        demo=demo,
        client=request.client,
        cwd=request.cwd,
        branch=request.git_branch,
        prompt=request.prompt,
    )


def register_session_heartbeat(
    session: Session,
    *,
    actor: User,
    session_id: str,
    demo: bool,
    client: str | None = None,
    cwd: str | None = None,
    branch: str | None = None,
    prompt: str = "",
    model_id: str | None = None,
) -> TaskforceSessionArchive:
    """Create or refresh the archive row used by active sessions and Sessions."""

    now = _now()
    archive = session.exec(
        select(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.organization_id == actor.organization_id)
        .where(TaskforceSessionArchive.is_demo == demo)
        .where(TaskforceSessionArchive.session_id == session_id)
    ).first()

    if archive is None:
        archive = TaskforceSessionArchive(
            session_id=session_id,
            actor_id=actor.id,
            organization_id=actor.organization_id,
            is_demo=demo,
            client=client,
            harness_label=client,
            model_id=model_id,
            cwd=cwd,
            repo=_repo_from_cwd(cwd),
            branch=branch,
            started_at=now,
            imported_at=now,
            created_at=now,
        )
    else:
        archive.cwd = cwd or archive.cwd
        archive.repo = _repo_from_cwd(cwd) or archive.repo
        archive.branch = branch or archive.branch
        archive.client = merge_session_client(archive.client, client)
        archive.harness_label = merge_session_client(archive.harness_label, client)
        archive.model_id = model_id or archive.model_id
        resurrect_archive_from_history(session, archive, actor, now=now)
    if archive.fleet_session_id is None:
        archive.fleet_session_id = get_or_create_default_fleet_session(
            session, actor
        ).id
    if prompt.strip():
        archive.title = " ".join(prompt.split())[:255]
        if archive.conversation_summary is None:
            archive.conversation_summary = summarize_opening_prompt(prompt)

    archive.last_seen_at = now
    archive.updated_at = now
    session.add(archive)

    # Append the prompt to the durable per-turn activity timeline (TF-247).
    # Deduped against this session's most recent row inside the helper.
    if prompt.strip():
        record_activity_prompt(
            session,
            actor=actor,
            session_id=session_id,
            prompt=prompt,
            demo=demo,
            fleet_session_id=archive.fleet_session_id,
            now=now,
        )
    return archive


def mark_session_turn_ended(
    session: Session,
    *,
    actor: User,
    session_id: str,
    demo: bool,
) -> TaskforceSessionArchive | None:
    """Record that a session finished a turn and is awaiting the next prompt.

    Driven by the Claude Code Stop hook. Advances both ``last_turn_ended_at``
    and ``last_seen_at`` so the session stays in the live roster but reports
    ``waiting`` (awaiting prompt) instead of ``running``. Returns ``None`` when
    no archive row exists yet (a turn-end before the session's first prompt).
    """

    now = _now()
    archive = session.exec(
        select(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.organization_id == actor.organization_id)
        .where(TaskforceSessionArchive.is_demo == demo)
        .where(TaskforceSessionArchive.session_id == session_id)
    ).first()
    if archive is None:
        return None

    archive.last_turn_ended_at = now
    archive.last_seen_at = now
    archive.updated_at = now
    session.add(archive)
    return archive


def _active_session_rows(
    session: Session,
    *,
    actor: User,
    demo: bool | None = None,
    exclude_session_id: str | None = None,
    limit: int = ROSTER_LIMIT,
    max_age: timedelta = MAX_AGE,
    now: datetime | None = None,
) -> tuple[list[TaskforceSessionArchive], datetime]:
    """Shared row fetch for the active-sessions and Sessions rosters.

    Scope: ``actor_id = actor``, same org (and ``is_demo`` space if given),
    ``ended_at IS NULL`` (cleanly-ended sessions are excluded outright — the
    ``max_age`` window is a backstop for "forgot to /exit", not the primary
    filter), and ``last_seen_at`` within ``max_age``. Capped at ``limit``
    rows, most recent first.
    """

    now = now or _now()
    cutoff = now - max_age

    statement = (
        select(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.actor_id == actor.id)
        .where(TaskforceSessionArchive.organization_id == actor.organization_id)
        .where(TaskforceSessionArchive.ended_at.is_(None))
        .where(TaskforceSessionArchive.last_seen_at.is_not(None))
        .where(TaskforceSessionArchive.last_seen_at >= cutoff)
    )
    if demo is not None:
        statement = statement.where(TaskforceSessionArchive.is_demo == demo)
    if exclude_session_id:
        statement = statement.where(
            TaskforceSessionArchive.session_id != exclude_session_id
        )
    statement = statement.order_by(desc(TaskforceSessionArchive.last_seen_at)).limit(
        limit
    )

    return list(session.exec(statement)), now


def get_active_sessions(
    session: Session,
    *,
    actor: User,
    demo: bool,
    exclude_session_id: str | None = None,
    limit: int = ROSTER_LIMIT,
    max_age: timedelta = MAX_AGE,
) -> list[TaskforceActiveSession]:
    """Return the actor's other currently-active sessions, most recent first."""

    rows, now = _active_session_rows(
        session,
        actor=actor,
        demo=demo,
        exclude_session_id=exclude_session_id,
        limit=limit,
        max_age=max_age,
    )
    if not rows:
        return []

    doc_ids = {row.active_document_id for row in rows if row.active_document_id}
    documents: dict[uuid.UUID, V2Document] = {}
    if doc_ids:
        documents = {
            doc.id: doc
            for doc in session.exec(
                select(V2Document).where(col(V2Document.id).in_(doc_ids))
            )
        }

    entries: list[TaskforceActiveSession] = []
    for row in rows:
        document = (
            documents.get(row.active_document_id) if row.active_document_id else None
        )
        last_seen_at = row.last_seen_at
        assert last_seen_at is not None  # filtered above
        minutes_ago = max(0, int((now - last_seen_at).total_seconds() // 60))
        entries.append(
            TaskforceActiveSession(
                session_id=row.session_id,
                cwd=row.cwd,
                active_document_id=row.active_document_id,
                title=document.title if document else None,
                summary_markdown=(document.ai_generated_summary or "")
                if document
                else (row.title or ""),
                last_seen_at=last_seen_at,
                minutes_ago=minutes_ago,
            )
        )
    return entries


def _uuid_values(values: list[str]) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    for value in values:
        try:
            result.append(uuid.UUID(value))
        except (TypeError, ValueError):
            continue
    return result


def _minutes_ago(now: datetime, value: datetime) -> int:
    normalized = value
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    return max(
        0, int((now - normalized.astimezone(timezone.utc)).total_seconds() // 60)
    )


# Maps the self-reported ``client`` provenance string (set by the hooks —
# see app/assets/taskforce-*-hooks) to the Fleet row chip kind.
_AGENT_KIND_BY_CLIENT = {
    "claude-code": "claude",
    "claude": "claude",
    "codex": "codex",
    "cursor": "cursor",
}


def _agent_kind(
    client: str | None,
    model_id: str | None,
    harness_label: str | None = None,
) -> str:
    """Classify the coding tool driving a session into a Fleet chip kind.

    Prefers hook-reported ``client`` / ``harness_label`` provenance. Only
    OpenAI-style ``model_id`` values are used as a last resort — never
    ``claude-*``, because Cursor and Claude Code share Anthropic models and
    inferring "claude" from the model alone mislabels Cursor sessions whenever
    ``client`` is briefly missing.
    """

    for value in (client, harness_label):
        kind = _AGENT_KIND_BY_CLIENT.get((value or "").strip().lower())
        if kind is not None:
            return kind
    model = (model_id or "").lower()
    if model.startswith(("gpt", "o1", "o3", "o4")):
        return "codex"
    return "other"


def _model_label(model_id: str | None) -> str | None:
    if not model_id:
        return None
    family, *rest = model_id.removeprefix("claude-").split("-", 1)
    if not family:
        return None
    name = "GPT" if family.lower() == "gpt" else family.capitalize()
    version = rest[0].replace("-", ".") if rest else ""
    return f"{name} {version}".strip()


def _repo_label(archive: TaskforceSessionArchive) -> str:
    cwd_parts = (archive.cwd or "").split("/")
    cwd_parts = [part for part in cwd_parts if part]
    return archive.repo or (cwd_parts[-1] if cwd_parts else "Unknown repo")


def _fleet_display_name(archive: TaskforceSessionArchive) -> str:
    if archive.display_name:
        return archive.display_name
    if archive.conversation_summary:
        return archive.conversation_summary
    return _model_label(archive.model_id) or _repo_label(archive)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fleet_status(
    minutes_ago: int,
    *,
    last_seen_at: datetime,
    last_turn_ended_at: datetime | None,
) -> str:
    """Server-derived Sessions state.

    Outside the live window the session is ``idle``. Within it, a turn-end at
    or after the last heartbeat means the agent finished its turn and is
    awaiting the next user prompt (``waiting``); otherwise a prompt arrived
    after the last turn end and a turn is in progress (``running``).
    """

    if minutes_ago >= int(FLEET_RUNNING_WINDOW.total_seconds() // 60):
        return "idle"
    if last_turn_ended_at is not None and _as_utc(last_turn_ended_at) >= _as_utc(
        last_seen_at
    ):
        return "waiting"
    return "running"


def active_sessions_for_actor(
    session: Session,
    *,
    actor: User,
    limit: int = ROSTER_LIMIT,
    now: datetime | None = None,
) -> list[TaskforceFleetAgentPublic]:
    """Return the actor's recent, non-ended sessions for the Sessions panel.

    Built on the same row query as :func:`get_active_sessions`, but not
    scoped to a single ``is_demo`` space (the Sessions panel shows all of the
    actor's sessions) and returns the richer ``TaskforceFleetAgentPublic``
    shape, including ``fleet_session_id``, ``referenced_document_ids`` and
    ``specialist_slug``.
    """

    archives, now_utc = _active_session_rows(
        session,
        actor=actor,
        demo=None,
        limit=limit,
        now=now,
    )
    return _fleet_agent_public_from_archive(
        session,
        actor=actor,
        archives=archives,
        now_utc=now_utc,
    )


def _fleet_agent_public_from_archive(
    session: Session,
    *,
    actor: User,
    archives: list[TaskforceSessionArchive],
    now_utc: datetime,
) -> list[TaskforceFleetAgentPublic]:
    referenced_by_session: dict[str, list[uuid.UUID]] = {}
    all_document_ids: set[uuid.UUID] = set()
    for archive in archives:
        referenced = _uuid_values(archive.referenced_document_ids or [])
        referenced_by_session[archive.session_id] = referenced
        all_document_ids.update(referenced)
        if archive.active_document_id is not None:
            all_document_ids.add(archive.active_document_id)

    documents_by_id: dict[uuid.UUID, V2Document] = {}
    if all_document_ids:
        documents = session.exec(
            select(V2Document)
            .where(col(V2Document.id).in_(all_document_ids))
            .where(V2Document.owner_id == actor.id)
        ).all()
        documents_by_id = {document.id: document for document in documents}

    specialist_slugs = {
        archive.specialist_slug for archive in archives if archive.specialist_slug
    }
    specialist_rule_counts: dict[str, int] = {}
    if specialist_slugs:
        specialists = session.exec(
            select(AgentSpecialist).where(
                col(AgentSpecialist.slug).in_(specialist_slugs)
            )
        ).all()
        specialist_rule_counts = {
            specialist.slug: len(specialist.instructions or [])
            for specialist in specialists
        }

    result: list[TaskforceFleetAgentPublic] = []
    for archive in archives:
        referenced = referenced_by_session[archive.session_id]
        active_document_id = archive.active_document_id
        if active_document_id is None:
            active_document_id = next(
                (
                    document_id
                    for document_id in reversed(referenced)
                    if document_id in documents_by_id
                ),
                None,
            )
        active_document = (
            documents_by_id.get(active_document_id)
            if active_document_id is not None
            else None
        )
        last_seen_at = archive.last_seen_at
        if last_seen_at is None:
            continue
        minutes_ago = _minutes_ago(now_utc, last_seen_at)

        result.append(
            TaskforceFleetAgentPublic(
                session_id=archive.session_id,
                fleet_session_id=archive.fleet_session_id,
                cwd=archive.cwd,
                active_document_id=active_document_id,
                referenced_document_ids=referenced,
                display_name=_fleet_display_name(archive),
                title=active_document.title if active_document is not None else None,
                summary_markdown=(
                    (
                        active_document.ai_generated_summary
                        or active_document.description
                        or ""
                    )
                    if active_document is not None
                    else ""
                ),
                last_seen_at=last_seen_at,
                minutes_ago=minutes_ago,
                status=_fleet_status(
                    minutes_ago,
                    last_seen_at=last_seen_at,
                    last_turn_ended_at=archive.last_turn_ended_at,
                ),
                started_at=archive.started_at,
                specialist_slug=archive.specialist_slug,
                specialist_rule_count=(
                    specialist_rule_counts.get(archive.specialist_slug)
                    if archive.specialist_slug
                    else None
                ),
                model_id=archive.model_id,
                agent_kind=_agent_kind(
                    archive.client,
                    archive.model_id,
                    archive.harness_label,
                ),
            )
        )

    return result


def history_agents_for_actor(
    session: Session,
    *,
    actor: User,
    limit: int = HISTORY_ROSTER_LIMIT,
    now: datetime | None = None,
) -> list[TaskforceFleetAgentPublic]:
    """Return inactive agent receipts stored in the actor's History session."""

    history = history_fleet_session_for_actor(session, actor)
    if history is None:
        return []

    now_utc = now or _now()
    archives = list(
        session.exec(
            select(TaskforceSessionArchive)
            .where(TaskforceSessionArchive.actor_id == actor.id)
            .where(TaskforceSessionArchive.fleet_session_id == history.id)
            .order_by(desc(TaskforceSessionArchive.last_seen_at))
            .limit(limit)
        ).all()
    )
    return _fleet_agent_public_from_archive(
        session,
        actor=actor,
        archives=archives,
        now_utc=now_utc,
    )
