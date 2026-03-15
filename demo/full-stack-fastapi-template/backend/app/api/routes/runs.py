import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core.cases import build_default_case_data, execution_has_column
from app.core.topics import refresh_topic_rollup
from app.models import (
    ArtifactPublic,
    EventCreate,
    EventPublic,
    EventsPublic,
    ExecutionArtifactLinkCreate,
    ExecutionArtifactLinkPublic,
    ExecutionArtifactLinksPublic,
    ExecutionDetailPublic,
    ExecutionPublic,
    ExecutionsPublic,
    Message,
    ExecutionStartPublic,
    ExecutionStartRequest,
    ExecutionUpdate,
    ThreadPublic,
)

router = APIRouter(prefix="/executions", tags=["executions"])

_UUID_RE = re.compile(
    r"\\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\b",
    flags=re.IGNORECASE,
)


def _is_missing_table_error(err: Exception) -> bool:
    message = str(err).lower()
    return "does not exist" in message and "relation" in message


def _is_missing_column_error(err: Exception, *, column: str) -> bool:
    message = str(err).lower()
    return "does not exist" in message and "column" in message and column.lower() in message


def _thread_has_intent_key_column(session: SessionDep) -> bool:
    # Keep /executions/start backward-compatible with older DB schemas. Mirrors routes/tasks.py.
    stmt = text(
        "select 1 "
        "from information_schema.columns "
        "where table_schema = 'public' and table_name = 'thread' and column_name = 'intent_key' "
        "limit 1"
    )
    return session.connection().execute(stmt).first() is not None


def _canonicalize_thread_title(title: str) -> str:
    # Keep this conservative: only strip UUID-like tokens and normalize whitespace.
    cleaned = _UUID_RE.sub("", title).strip()
    cleaned = re.sub(r"\\s+", " ", cleaned)
    return cleaned.strip() or title.strip()


def _default_intent_key(title: str) -> str:
    # Stable-ish machine key derived from the title, with UUIDs removed.
    base = _canonicalize_thread_title(title).lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    return base or "task"


@router.get("/", response_model=ExecutionsPublic)
def read_executions(
    session: SessionDep,
    current_user: CurrentUser,
    thread_id: uuid.UUID | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve Executions.
    """

    clauses: list[str] = []
    params: dict[str, Any] = {"skip": skip, "limit": limit}

    if thread_id:
        clauses.append("r.thread_id = :thread_id")
        params["thread_id"] = thread_id
    if status:
        status = status.strip()
        if status:
            clauses.append("r.status = :status")
            params["status"] = status

    where_sql = f" where {' and '.join(clauses)}" if clauses else ""

    try:
        count_stmt = text(f"select count(*) from public.execution r{where_sql}")
        count = session.connection().execute(count_stmt, params).scalar_one()

        data_stmt = text(
            "select "
            "r.id, r.thread_id, r.targets, r.started_at, r.ended_at, r.status, r.summary "
            "from public.execution r"
            f"{where_sql} "
            "order by r.started_at desc nulls last "
            "offset :skip limit :limit"
        )
        rows = session.connection().execute(data_stmt, params).mappings().all()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return ExecutionsPublic(data=[], count=0)
        raise

    executions = [ExecutionPublic(**dict(row)) for row in rows]
    return ExecutionsPublic(data=executions, count=count)


@router.post("/start", response_model=ExecutionStartPublic, status_code=201)
def start_execution(
    session: SessionDep,
    current_user: CurrentUser,
    payload: ExecutionStartRequest,
) -> Any:
    """
    Start an Execution, reusing an existing Thread when appropriate.

    This is the primary "Thread vs Execution" grouping mechanism:
    - Thread groups repeated work by (workflow_key, intent_key).
    - Execution captures a single attempt with per-instance targets.
    """

    thread_in = payload.thread
    execution_in = payload.execution

    workflow_key = thread_in.workflow_key.strip()
    title_raw = thread_in.title.strip()
    if not workflow_key:
        raise HTTPException(status_code=422, detail="workflow_key must not be empty")
    if not title_raw:
        raise HTTPException(status_code=422, detail="Title must not be empty")

    intent_key = (
        thread_in.intent_key.strip()
        if isinstance(thread_in.intent_key, str) and thread_in.intent_key.strip()
        else _default_intent_key(title_raw)
    )
    thread_title = _canonicalize_thread_title(title_raw)
    has_intent_key = _thread_has_intent_key_column(session)

    now = datetime.now(timezone.utc)
    reuse_within_seconds = payload.reuse_within_seconds

    thread_row = None
    reused_thread = False
    try:
        if has_intent_key:
            stmt = text(
                "select "
                "t.id, t.title, t.workflow_key, t.intent_key, t.goal, t.acceptance_criteria, "
                "t.systems_touched, t.risk_level, t.status, t.created_at, t.last_touched_at "
                "from public.thread t "
                "where t.workflow_key = :workflow_key and t.intent_key = :intent_key "
                "order by t.last_touched_at desc nulls last "
                "limit 1"
            )
            params = {"workflow_key": workflow_key, "intent_key": intent_key}
        else:
            # Older schema: no intent_key column. Fall back to grouping by (workflow_key, canonicalized title).
            stmt = text(
                "select "
                "t.id, t.title, t.workflow_key, t.goal, t.acceptance_criteria, "
                "t.systems_touched, t.risk_level, t.status, t.created_at, t.last_touched_at "
                "from public.thread t "
                "where t.workflow_key = :workflow_key and t.title = :title "
                "order by t.last_touched_at desc nulls last "
                "limit 1"
            )
            params = {"workflow_key": workflow_key, "title": thread_title}
        thread_row = session.connection().execute(stmt, params).mappings().first()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=501, detail="Threads table not initialized")
        raise

    if thread_row is not None and reuse_within_seconds is not None:
        last_touched_at = thread_row.get("last_touched_at")
        if last_touched_at is not None:
            age_s = (now - last_touched_at).total_seconds()
            if age_s > reuse_within_seconds:
                thread_row = None

    # Create a new Thread if none is eligible for reuse.
    if thread_row is None:
        # Keep behavior stable even if clients send empty strings.
        goal = thread_in.goal.strip() if isinstance(thread_in.goal, str) and thread_in.goal.strip() else None
        acceptance_criteria = (
            thread_in.acceptance_criteria.strip()
            if isinstance(thread_in.acceptance_criteria, str) and thread_in.acceptance_criteria.strip()
            else None
        )
        risk_level = thread_in.risk_level.strip() or "read_only"
        status = thread_in.status.strip() or "open"
        systems_touched = thread_in.systems_touched or {}

        thread_id = uuid.uuid4()
        try:
            if has_intent_key:
                insert_stmt = text(
                    "insert into public.thread ("
                    "id, title, workflow_key, intent_key, goal, acceptance_criteria, systems_touched, risk_level, status"
                    ") values ("
                    ":id, :title, :workflow_key, :intent_key, :goal, :acceptance_criteria, cast(:systems_touched as jsonb), :risk_level, :status"
                    ") returning "
                    "id, title, workflow_key, intent_key, goal, acceptance_criteria, systems_touched, "
                    "risk_level, status, created_at, last_touched_at"
                )
            else:
                insert_stmt = text(
                    "insert into public.thread ("
                    "id, title, workflow_key, goal, acceptance_criteria, systems_touched, risk_level, status"
                    ") values ("
                    ":id, :title, :workflow_key, :goal, :acceptance_criteria, cast(:systems_touched as jsonb), :risk_level, :status"
                    ") returning "
                    "id, title, workflow_key, goal, acceptance_criteria, systems_touched, "
                    "risk_level, status, created_at, last_touched_at"
                )
            thread_row = (
                session.connection()
                .execute(
                    insert_stmt,
                    (
                        {
                            "id": thread_id,
                            "title": thread_title,
                            "workflow_key": workflow_key,
                            "intent_key": intent_key,
                            "goal": goal,
                            "acceptance_criteria": acceptance_criteria,
                            "systems_touched": json.dumps(systems_touched),
                            "risk_level": risk_level,
                            "status": status,
                        }
                        if has_intent_key
                        else {
                            "id": thread_id,
                            "title": thread_title,
                            "workflow_key": workflow_key,
                            "goal": goal,
                            "acceptance_criteria": acceptance_criteria,
                            "systems_touched": json.dumps(systems_touched),
                            "risk_level": risk_level,
                            "status": status,
                        }
                    ),
                )
                .mappings()
                .first()
            )
        except ProgrammingError as e:
            if _is_missing_table_error(e):
                raise HTTPException(status_code=501, detail="Threads table not initialized")
            raise

        if thread_row is None:
            raise HTTPException(status_code=500, detail="Failed to create thread")
    else:
        reused_thread = True

    thread_id = thread_row["id"]

    # Create the Execution.
    targets = execution_in.targets or []
    execution_status = execution_in.status.strip() or "running"
    summary = (
        execution_in.summary.strip()
        if isinstance(execution_in.summary, str) and execution_in.summary.strip()
        else thread_title
    )
    execution_id = uuid.uuid4()

    has_execution_updated_at = execution_has_column(session, "updated_at")
    has_case_data = execution_has_column(session, "case_data")
    has_context_pack_snapshot = execution_has_column(session, "context_pack_snapshot")
    default_case_data = build_default_case_data(
        {"id": execution_id, "summary": summary, "actor_id": current_user.id},
        {"id": thread_id, "title": thread_title},
    )
    context_pack_snapshot = {"topic_id": str(thread_id), "case_id": str(execution_id)}

    try:
        execution_columns = ["id", "thread_id", "targets", "status", "summary"]
        execution_values = [":id", ":thread_id", "cast(:targets as jsonb)", ":status", ":summary"]
        execution_params: dict[str, Any] = {
            "id": execution_id,
            "thread_id": thread_id,
            "targets": json.dumps(targets),
            "status": execution_status,
            "summary": summary,
        }
        if has_execution_updated_at:
            execution_columns.append("updated_at")
            execution_values.append("now()")
        if has_case_data:
            execution_columns.append("case_data")
            execution_values.append("cast(:case_data as jsonb)")
            execution_params["case_data"] = json.dumps(default_case_data)
        if has_context_pack_snapshot:
            execution_columns.append("context_pack_snapshot")
            execution_values.append("cast(:context_pack_snapshot as jsonb)")
            execution_params["context_pack_snapshot"] = json.dumps(context_pack_snapshot)

        execution_stmt = text(
            "insert into public.execution ("
            + ", ".join(execution_columns)
            + ") values ("
            + ", ".join(execution_values)
            + ") returning id, thread_id, targets, started_at, ended_at, status, summary"
        )
        execution_row = (
            session.connection()
            .execute(execution_stmt, execution_params)
            .mappings()
            .first()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=501, detail="Executions table not initialized")
        raise

    if execution_row is None:
        raise HTTPException(status_code=500, detail="Failed to create execution")

    # Touch the Thread (and reopen "done" threads) to keep ordering/grouping sensible.
    try:
        if has_intent_key:
            touch_stmt = text(
                "update public.thread "
                "set last_touched_at = now(), status = (case when status = 'done' then 'open' else status end) "
                "where id = :thread_id "
                "returning "
                "id, title, workflow_key, intent_key, goal, acceptance_criteria, systems_touched, "
                "risk_level, status, created_at, last_touched_at"
            )
        else:
            touch_stmt = text(
                "update public.thread "
                "set last_touched_at = now(), status = (case when status = 'done' then 'open' else status end) "
                "where id = :thread_id "
                "returning "
                "id, title, workflow_key, goal, acceptance_criteria, systems_touched, "
                "risk_level, status, created_at, last_touched_at"
            )
        touched = (
            session.connection().execute(touch_stmt, {"thread_id": thread_id}).mappings().first()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=501, detail="Threads table not initialized")
        raise

    refresh_topic_rollup(session, thread_id, persist=True)
    session.commit()

    thread_public = ThreadPublic(**dict(touched or thread_row))
    execution_public = ExecutionPublic(**dict(execution_row))
    return ExecutionStartPublic(
        thread=thread_public,
        execution=execution_public,
        reused_thread=reused_thread,
    )


@router.get("/{execution_id}", response_model=ExecutionPublic)
def read_execution(session: SessionDep, current_user: CurrentUser, execution_id: uuid.UUID) -> Any:
    """
    Get an Execution by ID.
    """

    try:
        stmt = text(
            "select "
            "e.id, e.thread_id, e.targets, e.started_at, e.ended_at, e.status, e.summary "
            "from public.execution e "
            "where e.id = :execution_id "
            "limit 1"
        )
        row = (
            session.connection()
            .execute(stmt, {"execution_id": execution_id})
            .mappings()
            .first()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Execution not found")
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return ExecutionPublic(**dict(row))


@router.patch("/{execution_id}", response_model=ExecutionPublic)
def update_execution(
    session: SessionDep,
    current_user: CurrentUser,
    execution_id: uuid.UUID,
    execution_in: ExecutionUpdate,
) -> Any:
    """
    Update an Execution.
    """

    update = execution_in.model_dump(exclude_unset=True)
    if not update:
        raise HTTPException(status_code=422, detail="No fields to update")

    clauses: list[str] = []
    params: dict[str, Any] = {"execution_id": execution_id}

    if "targets" in update:
        targets = update.get("targets")
        clauses.append("targets = cast(:targets as jsonb)")
        params["targets"] = json.dumps(targets or [])

    if "status" in update:
        status = update.get("status")
        if status is not None:
            status = status.strip()
            if not status:
                raise HTTPException(status_code=422, detail="status must not be empty")
        clauses.append("status = :status")
        params["status"] = status

    if "summary" in update:
        summary = update.get("summary")
        if isinstance(summary, str):
            summary = summary.strip() or None
        clauses.append("summary = :summary")
        params["summary"] = summary

    if "ended_at" in update:
        ended_at = update.get("ended_at")
        clauses.append("ended_at = :ended_at")
        params["ended_at"] = ended_at

    if execution_has_column(session, "updated_at"):
        clauses.append("updated_at = now()")

    # Convenience: if status is being set to a terminal state and ended_at wasn't explicitly set, set it.
    if "status" in update and "ended_at" not in update:
        s = update.get("status")
        if isinstance(s, str) and s.strip().lower() in {"done", "aborted", "failed", "success", "error"}:
            clauses.append("ended_at = coalesce(ended_at, now())")

    if not clauses:
        raise HTTPException(status_code=422, detail="No valid fields to update")

    try:
        stmt = text(
            "update public.execution "
            f"set {', '.join(clauses)} "
            "where id = :execution_id "
            "returning id, thread_id, targets, started_at, ended_at, status, summary"
        )
        row = (
            session.connection()
            .execute(stmt, params)
            .mappings()
            .first()
        )
        if row is not None:
            refresh_topic_rollup(session, row["thread_id"], persist=True)
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Execution not found")
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return ExecutionPublic(**dict(row))


@router.delete("/{execution_id}", response_model=Message)
def delete_execution(session: SessionDep, current_user: CurrentUser, execution_id: uuid.UUID) -> Any:
    """
    Delete an Execution.

    Note: restricted to superusers; deleting executions removes audit trail for that execution.
    """

    get_current_active_superuser(current_user)
    try:
        stmt = text("delete from public.execution where id = :execution_id returning id")
        deleted = session.connection().execute(stmt, {"execution_id": execution_id}).first()
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Execution not found")
        raise

    if deleted is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return Message(message="Execution deleted successfully")


@router.get("/{execution_id}/events", response_model=EventsPublic)
def read_execution_events(
    session: SessionDep,
    current_user: CurrentUser,
    execution_id: uuid.UUID,
    skip: int = 0,
    limit: int = 1000,
) -> Any:
    """
    Retrieve Events for an Execution.
    """

    try:
        count_stmt = text("select count(*) from public.event e where e.execution_id = :execution_id")
        count = (
            session.connection()
            .execute(count_stmt, {"execution_id": execution_id})
            .scalar_one()
        )
        stmt = text(
            "select e.id, e.execution_id, e.ts, e.type, e.message, e.data, e.supersedes_event_id "
            "from public.event e "
            "where e.execution_id = :execution_id "
            "order by e.ts asc nulls last, e.id asc "
            "offset :skip limit :limit"
        )
        rows = (
            session.connection()
            .execute(stmt, {"execution_id": execution_id, "skip": skip, "limit": limit})
            .mappings()
            .all()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return EventsPublic(data=[], count=0)
        raise

    events = [EventPublic(**dict(row)) for row in rows]
    return EventsPublic(data=events, count=count)


@router.post("/{execution_id}/events", response_model=EventPublic, status_code=201)
def create_execution_event(
    session: SessionDep,
    current_user: CurrentUser,
    execution_id: uuid.UUID,
    event_in: EventCreate,
) -> Any:
    """
    Append an Event (audit log) to an Execution.
    """

    type_ = event_in.type.strip()
    if not type_:
        raise HTTPException(status_code=422, detail="type must not be empty")

    payload = event_in.data or {}
    message = event_in.message.strip() if isinstance(event_in.message, str) and event_in.message.strip() else None
    supersedes_event_id = event_in.supersedes_event_id

    try:
        execution_lookup = session.connection().execute(
            text("select e.thread_id from public.execution e where e.id = :execution_id limit 1"),
            {"execution_id": execution_id},
        ).mappings().first()
        if execution_lookup is None:
            raise HTTPException(status_code=404, detail="Execution not found")

        stmt = text(
            "insert into public.event (execution_id, ts, type, message, data, supersedes_event_id) "
            "values (:execution_id, coalesce(:ts, now()), :type, :message, cast(:data as jsonb), :supersedes_event_id) "
            "returning id, execution_id, ts, type, message, data, supersedes_event_id"
        )
        row = (
            session.connection()
            .execute(
                stmt,
                {
                    "execution_id": execution_id,
                    "ts": event_in.ts,
                    "type": type_,
                    "message": message,
                    "data": json.dumps(payload),
                    "supersedes_event_id": supersedes_event_id,
                },
            )
            .mappings()
            .first()
        )

        # Best-effort: improve the Execution summary for UIs that list executions by summary.
        # Only sets a summary when it's missing or still on a generic placeholder.
        summary_candidate = message
        if summary_candidate is None:
            intent = payload.get("intent")
            if isinstance(intent, str) and intent.strip():
                summary_candidate = intent.strip()
        if isinstance(summary_candidate, str) and summary_candidate.strip():
            summary_candidate = summary_candidate.strip()[:255]
            session.connection().execute(
                text(
                    "update public.execution "
                    "set summary = :summary "
                    "where id = :execution_id and (summary is null or btrim(summary) = '' or summary = 'Execution')"
                ),
                {"execution_id": execution_id, "summary": summary_candidate},
            )
        if execution_has_column(session, "updated_at"):
            session.connection().execute(
                text("update public.execution set updated_at = now() where id = :execution_id"),
                {"execution_id": execution_id},
            )
        refresh_topic_rollup(session, execution_lookup["thread_id"], persist=True)
        session.commit()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Invalid event linkage")
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Execution not found")
        raise

    if row is None:
        raise HTTPException(status_code=500, detail="Failed to create event")
    return EventPublic(**dict(row))


@router.post("/{execution_id}/events/{event_id}/supersede", response_model=EventPublic, status_code=201)
def supersede_execution_event(
    session: SessionDep,
    current_user: CurrentUser,
    execution_id: uuid.UUID,
    event_id: int,
    event_in: EventCreate,
) -> Any:
    """
    "Update" an Event by creating a new Event that supersedes it.
    """

    try:
        existing = (
            session.connection()
            .execute(
                text(
                    "select 1 from public.event e "
                    "where e.id = :event_id and e.execution_id = :execution_id "
                    "limit 1"
                ),
                {"event_id": event_id, "execution_id": execution_id},
            )
            .first()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Event not found")
        raise

    if existing is None:
        raise HTTPException(status_code=404, detail="Event not found")

    patched = EventCreate(
        ts=event_in.ts,
        type=event_in.type,
        message=event_in.message,
        data=event_in.data,
        supersedes_event_id=event_id,
    )
    return create_execution_event(
        session=session,
        current_user=current_user,
        execution_id=execution_id,
        event_in=patched,
    )


@router.delete("/{execution_id}/events/{event_id}", response_model=Message)
def delete_execution_event(
    session: SessionDep,
    current_user: CurrentUser,
    execution_id: uuid.UUID,
    event_id: int,
) -> Any:
    """
    Delete an Event.

    Note: restricted to superusers; prefer superseding events instead of deleting.
    """

    get_current_active_superuser(current_user)
    try:
        stmt = text(
            "delete from public.event "
            "where id = :event_id and execution_id = :execution_id "
            "returning id"
        )
        deleted = (
            session.connection()
            .execute(stmt, {"event_id": event_id, "execution_id": execution_id})
            .first()
        )
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Event not found")
        raise

    if deleted is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return Message(message="Event deleted successfully")


@router.get("/{execution_id}/artifact-links", response_model=ExecutionArtifactLinksPublic)
def read_execution_artifact_links(
    session: SessionDep,
    current_user: CurrentUser,
    execution_id: uuid.UUID,
    skip: int = 0,
    limit: int = 1000,
) -> Any:
    """
    Retrieve artifact links for an Execution.
    """

    try:
        count_stmt = text(
            "select count(*) from public.execution_artifact_link l where l.execution_id = :execution_id"
        )
        count = session.connection().execute(count_stmt, {"execution_id": execution_id}).scalar_one()

        stmt = text(
            "select "
            "l.relation as relation, "
            "l.created_at as created_at, "
            "a.id as artifact_id, "
            "a.workflow_key as workflow_key, "
            "a.kind as kind, "
            "a.title as title, "
            "a.body_mdc as body_mdc, "
            "a.tags as tags, "
            "a.source_refs as source_refs, "
            "a.promotion_mode as promotion_mode, "
            "a.created_at as artifact_created_at, "
            "a.last_used_at as last_used_at, "
            "a.superseded_by_id as superseded_by_id "
            "from public.execution_artifact_link l "
            "join public.artifact a on a.id = l.artifact_id "
            "where l.execution_id = :execution_id "
            "order by l.relation asc, l.created_at desc "
            "offset :skip limit :limit"
        )
        rows = (
            session.connection()
            .execute(stmt, {"execution_id": execution_id, "skip": skip, "limit": limit})
            .mappings()
            .all()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return ExecutionArtifactLinksPublic(data=[], count=0)
        raise

    links: list[ExecutionArtifactLinkPublic] = []
    for row in rows:
        artifact = ArtifactPublic(
            id=row["artifact_id"],
            workflow_key=row["workflow_key"],
            kind=row["kind"],
            title=row["title"],
            body_mdc=row["body_mdc"],
            tags=row.get("tags") or {},
            source_refs=row.get("source_refs") or [],
            promotion_mode=row["promotion_mode"],
            created_at=row["artifact_created_at"],
            last_used_at=row["last_used_at"],
            superseded_by_id=row["superseded_by_id"],
        )
        links.append(
            ExecutionArtifactLinkPublic(
                relation=row["relation"],
                created_at=row["created_at"],
                artifact=artifact,
            )
        )

    return ExecutionArtifactLinksPublic(data=links, count=count)


@router.post("/{execution_id}/artifact-links", response_model=ExecutionArtifactLinkPublic, status_code=201)
def create_execution_artifact_link(
    session: SessionDep,
    current_user: CurrentUser,
    execution_id: uuid.UUID,
    link_in: ExecutionArtifactLinkCreate,
) -> Any:
    """
    Create an artifact link (execution_artifact_link) for an Execution.
    """

    created_at = link_in.created_at
    relation = link_in.relation
    artifact_id = link_in.artifact_id

    try:
        exists = session.connection().execute(
            text("select 1 from public.execution e where e.id = :execution_id limit 1"),
            {"execution_id": execution_id},
        ).first()
        if exists is None:
            raise HTTPException(status_code=404, detail="Execution not found")

        a_exists = session.connection().execute(
            text("select 1 from public.artifact a where a.id = :id limit 1"),
            {"id": artifact_id},
        ).first()
        if a_exists is None:
            raise HTTPException(status_code=404, detail="Artifact not found")

        stmt = text(
            "insert into public.execution_artifact_link (execution_id, artifact_id, relation, created_at) "
            "values (:execution_id, :artifact_id, :relation, coalesce(:created_at, now())) "
            "on conflict (execution_id, artifact_id, relation) do update set "
            "created_at = least(public.execution_artifact_link.created_at, excluded.created_at)"
        )
        session.connection().execute(
            stmt,
            {
                "execution_id": execution_id,
                "artifact_id": artifact_id,
                "relation": relation,
                "created_at": created_at,
            },
        )

        if relation == "used":
            session.connection().execute(
                text("update public.artifact set last_used_at = now() where id = :id"),
                {"id": artifact_id},
            )

        row_stmt = text(
            "select "
            "l.relation as relation, "
            "l.created_at as created_at, "
            "a.id as artifact_id, "
            "a.workflow_key as workflow_key, "
            "a.kind as kind, "
            "a.title as title, "
            "a.body_mdc as body_mdc, "
            "a.tags as tags, "
            "a.source_refs as source_refs, "
            "a.promotion_mode as promotion_mode, "
            "a.created_at as artifact_created_at, "
            "a.last_used_at as last_used_at, "
            "a.superseded_by_id as superseded_by_id "
            "from public.execution_artifact_link l "
            "join public.artifact a on a.id = l.artifact_id "
            "where l.execution_id = :execution_id and l.artifact_id = :artifact_id and l.relation = :relation "
            "limit 1"
        )
        row = (
            session.connection()
            .execute(
                row_stmt,
                {"execution_id": execution_id, "artifact_id": artifact_id, "relation": relation},
            )
            .mappings()
            .first()
        )
        session.commit()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Invalid artifact link")
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Execution not found")
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="Artifact link not created")

    artifact = ArtifactPublic(
        id=row["artifact_id"],
        workflow_key=row["workflow_key"],
        kind=row["kind"],
        title=row["title"],
        body_mdc=row["body_mdc"],
        tags=row.get("tags") or {},
        source_refs=row.get("source_refs") or [],
        promotion_mode=row["promotion_mode"],
        created_at=row["artifact_created_at"],
        last_used_at=row["last_used_at"],
        superseded_by_id=row["superseded_by_id"],
    )
    return ExecutionArtifactLinkPublic(
        relation=row["relation"],
        created_at=row["created_at"],
        artifact=artifact,
    )


@router.delete("/{execution_id}/artifact-links/{artifact_id}", response_model=Message)
def delete_execution_artifact_link(
    session: SessionDep,
    current_user: CurrentUser,
    execution_id: uuid.UUID,
    artifact_id: uuid.UUID,
    relation: str,
) -> Any:
    """
    Delete an artifact link (execution_artifact_link).

    Note: restricted to superusers; deleting links harms auditability.
    """

    get_current_active_superuser(current_user)
    relation = relation.strip()
    if not relation:
        raise HTTPException(status_code=422, detail="relation must not be empty")

    try:
        stmt = text(
            "delete from public.execution_artifact_link "
            "where execution_id = :execution_id and artifact_id = :artifact_id and relation = :relation "
            "returning 1"
        )
        deleted = (
            session.connection()
            .execute(
                stmt,
                {"execution_id": execution_id, "artifact_id": artifact_id, "relation": relation},
            )
            .first()
        )
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Artifact link not found")
        raise

    if deleted is None:
        raise HTTPException(status_code=404, detail="Artifact link not found")
    return Message(message="Artifact link deleted successfully")


@router.get("/{execution_id}/detail", response_model=ExecutionDetailPublic)
def read_execution_detail(
    session: SessionDep,
    current_user: CurrentUser,
    execution_id: uuid.UUID,
) -> Any:
    """
    Retrieve an Execution, its Thread, its append-only Events, and its artifact links.
    """

    try:
        execution_stmt = text(
            "select "
            "e.id, e.thread_id, e.targets, e.started_at, e.ended_at, e.status, e.summary "
            "from public.execution e "
            "where e.id = :execution_id "
            "limit 1"
        )
        execution_row = (
            session.connection()
            .execute(execution_stmt, {"execution_id": execution_id})
            .mappings()
            .first()
        )
        if execution_row is None:
            raise HTTPException(status_code=404, detail="Execution not found")

        thread_stmt = text(
            "select "
            "t.id, t.title, t.workflow_key, t.intent_key, t.goal, t.acceptance_criteria, "
            "t.systems_touched, t.risk_level, t.status, t.created_at, t.last_touched_at "
            "from public.thread t "
            "where t.id = :thread_id "
            "limit 1"
        )
        thread_row = (
            session.connection()
            .execute(thread_stmt, {"thread_id": execution_row["thread_id"]})
            .mappings()
            .first()
        )
        if thread_row is None:
            raise HTTPException(status_code=404, detail="Thread not found")

        events_stmt = text(
            "select "
            "e.id, e.execution_id, e.ts, e.type, e.message, e.data, e.supersedes_event_id "
            "from public.event e "
            "where e.execution_id = :execution_id "
            "order by e.ts asc nulls last, e.id asc"
        )
        event_rows = (
            session.connection()
            .execute(events_stmt, {"execution_id": execution_id})
            .mappings()
            .all()
        )

        links_stmt = text(
            "select "
            "l.relation as relation, "
            "l.created_at as created_at, "
            "a.id as artifact_id, "
            "a.workflow_key as workflow_key, "
            "a.kind as kind, "
            "a.title as title, "
            "a.body_mdc as body_mdc, "
            "a.tags as tags, "
            "a.source_refs as source_refs, "
            "a.promotion_mode as promotion_mode, "
            "a.created_at as artifact_created_at, "
            "a.last_used_at as last_used_at, "
            "a.superseded_by_id as superseded_by_id "
            "from public.execution_artifact_link l "
            "join public.artifact a on a.id = l.artifact_id "
            "where l.execution_id = :execution_id "
            "order by l.relation asc, l.created_at desc"
        )
        link_rows = (
            session.connection()
            .execute(links_stmt, {"execution_id": execution_id})
            .mappings()
            .all()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Execution not found")
        raise

    execution = ExecutionPublic(**dict(execution_row))
    thread = ThreadPublic(**dict(thread_row))
    events = [EventPublic(**dict(row)) for row in event_rows]

    links: list[ExecutionArtifactLinkPublic] = []
    for row in link_rows:
        artifact = ArtifactPublic(
            id=row["artifact_id"],
            workflow_key=row["workflow_key"],
            kind=row["kind"],
            title=row["title"],
            body_mdc=row["body_mdc"],
            tags=row.get("tags") or {},
            source_refs=row.get("source_refs") or [],
            promotion_mode=row["promotion_mode"],
            created_at=row["artifact_created_at"],
            last_used_at=row["last_used_at"],
            superseded_by_id=row["superseded_by_id"],
        )
        links.append(
            ExecutionArtifactLinkPublic(
                relation=row["relation"],
                created_at=row["created_at"],
                artifact=artifact,
            )
        )

    return ExecutionDetailPublic(
        execution=execution,
        thread=thread,
        events=events,
        artifact_links=links,
    )
