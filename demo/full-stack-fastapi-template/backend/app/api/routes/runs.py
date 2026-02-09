import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.models import (
    LibraryItemPublic,
    Message,
    RunDetailPublic,
    RunEventCreate,
    RunEventPublic,
    RunEventsPublic,
    RunMemoryLinkCreate,
    RunMemoryLinkPublic,
    RunMemoryLinksPublic,
    RunPublic,
    RunsPublic,
    RunStartPublic,
    RunStartRequest,
    RunUpdate,
    TaskPublic,
)

router = APIRouter(prefix="/runs", tags=["runs"])

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


def _task_has_intent_key_column(session: SessionDep) -> bool:
    # Keep /runs/start backward-compatible with older DB schemas. Mirrors routes/tasks.py.
    stmt = text(
        "select 1 "
        "from information_schema.columns "
        "where table_schema = 'public' and table_name = 'task' and column_name = 'intent_key' "
        "limit 1"
    )
    return session.connection().execute(stmt).first() is not None


def _canonicalize_task_title(title: str) -> str:
    # Keep this conservative: only strip UUID-like tokens and normalize whitespace.
    cleaned = _UUID_RE.sub("", title).strip()
    cleaned = re.sub(r"\\s+", " ", cleaned)
    return cleaned.strip() or title.strip()


def _default_intent_key(title: str) -> str:
    # Stable-ish machine key derived from the title, with UUIDs removed.
    base = _canonicalize_task_title(title).lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    return base or "task"


@router.get("/", response_model=RunsPublic)
def read_runs(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve Runs.
    """

    clauses: list[str] = []
    params: dict[str, Any] = {"skip": skip, "limit": limit}

    if task_id:
        clauses.append("r.task_id = :task_id")
        params["task_id"] = task_id
    if status:
        status = status.strip()
        if status:
            clauses.append("r.status = :status")
            params["status"] = status

    where_sql = f" where {' and '.join(clauses)}" if clauses else ""

    try:
        count_stmt = text(f"select count(*) from public.run r{where_sql}")
        count = session.connection().execute(count_stmt, params).scalar_one()

        data_stmt = text(
            "select "
            "r.id, r.task_id, r.targets, r.started_at, r.ended_at, r.status, r.summary "
            "from public.run r"
            f"{where_sql} "
            "order by r.started_at desc nulls last "
            "offset :skip limit :limit"
        )
        rows = session.connection().execute(data_stmt, params).mappings().all()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return RunsPublic(data=[], count=0)
        raise

    runs = [RunPublic(**dict(row)) for row in rows]
    return RunsPublic(data=runs, count=count)


@router.post("/start", response_model=RunStartPublic, status_code=201)
def start_run(
    session: SessionDep,
    current_user: CurrentUser,
    payload: RunStartRequest,
) -> Any:
    """
    Start a Run, reusing an existing Task when appropriate.

    This is the primary "Task vs Run" grouping mechanism:
    - Task groups repeated work by (workflow_key, intent_key).
    - Run captures a single execution/attempt with per-instance targets.
    """

    task_in = payload.task
    run_in = payload.run

    workflow_key = task_in.workflow_key.strip()
    title_raw = task_in.title.strip()
    if not workflow_key:
        raise HTTPException(status_code=422, detail="workflow_key must not be empty")
    if not title_raw:
        raise HTTPException(status_code=422, detail="Title must not be empty")

    intent_key = (
        task_in.intent_key.strip()
        if isinstance(task_in.intent_key, str) and task_in.intent_key.strip()
        else _default_intent_key(title_raw)
    )
    task_title = _canonicalize_task_title(title_raw)
    has_intent_key = _task_has_intent_key_column(session)

    now = datetime.now(timezone.utc)
    reuse_within_seconds = payload.reuse_within_seconds

    task_row = None
    reused_task = False
    try:
        if has_intent_key:
            stmt = text(
                "select "
                "t.id, t.title, t.workflow_key, t.intent_key, t.goal, t.acceptance_criteria, "
                "t.systems_touched, t.risk_level, t.status, t.created_at, t.last_touched_at "
                "from public.task t "
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
                "from public.task t "
                "where t.workflow_key = :workflow_key and t.title = :title "
                "order by t.last_touched_at desc nulls last "
                "limit 1"
            )
            params = {"workflow_key": workflow_key, "title": task_title}
        task_row = session.connection().execute(stmt, params).mappings().first()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=501, detail="Tasks table not initialized")
        raise

    if task_row is not None and reuse_within_seconds is not None:
        last_touched_at = task_row.get("last_touched_at")
        if last_touched_at is not None:
            age_s = (now - last_touched_at).total_seconds()
            if age_s > reuse_within_seconds:
                task_row = None

    # Create a new Task if none is eligible for reuse.
    if task_row is None:
        # Keep behavior stable even if clients send empty strings.
        goal = task_in.goal.strip() if isinstance(task_in.goal, str) and task_in.goal.strip() else None
        acceptance_criteria = (
            task_in.acceptance_criteria.strip()
            if isinstance(task_in.acceptance_criteria, str) and task_in.acceptance_criteria.strip()
            else None
        )
        risk_level = task_in.risk_level.strip() or "read_only"
        status = task_in.status.strip() or "open"
        systems_touched = task_in.systems_touched or {}

        task_id = uuid.uuid4()
        try:
            if has_intent_key:
                insert_stmt = text(
                    "insert into public.task ("
                    "id, title, workflow_key, intent_key, goal, acceptance_criteria, systems_touched, risk_level, status"
                    ") values ("
                    ":id, :title, :workflow_key, :intent_key, :goal, :acceptance_criteria, cast(:systems_touched as jsonb), :risk_level, :status"
                    ") returning "
                    "id, title, workflow_key, intent_key, goal, acceptance_criteria, systems_touched, "
                    "risk_level, status, created_at, last_touched_at"
                )
            else:
                insert_stmt = text(
                    "insert into public.task ("
                    "id, title, workflow_key, goal, acceptance_criteria, systems_touched, risk_level, status"
                    ") values ("
                    ":id, :title, :workflow_key, :goal, :acceptance_criteria, cast(:systems_touched as jsonb), :risk_level, :status"
                    ") returning "
                    "id, title, workflow_key, goal, acceptance_criteria, systems_touched, "
                    "risk_level, status, created_at, last_touched_at"
                )
            task_row = (
                session.connection()
                .execute(
                    insert_stmt,
                    (
                        {
                            "id": task_id,
                            "title": task_title,
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
                            "id": task_id,
                            "title": task_title,
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
                raise HTTPException(status_code=501, detail="Tasks table not initialized")
            raise

        if task_row is None:
            raise HTTPException(status_code=500, detail="Failed to create task")
    else:
        reused_task = True

    task_id = task_row["id"]

    # Create the Run.
    targets = run_in.targets or []
    run_status = run_in.status.strip() or "running"
    summary = run_in.summary.strip() if isinstance(run_in.summary, str) and run_in.summary.strip() else None
    run_id = uuid.uuid4()

    try:
        run_stmt = text(
            "insert into public.run (id, task_id, targets, status, summary) "
            "values (:id, :task_id, cast(:targets as jsonb), :status, :summary) "
            "returning id, task_id, targets, started_at, ended_at, status, summary"
        )
        run_row = (
            session.connection()
            .execute(
                run_stmt,
                {
                    "id": run_id,
                    "task_id": task_id,
                    "targets": json.dumps(targets),
                    "status": run_status,
                    "summary": summary,
                },
            )
            .mappings()
            .first()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=501, detail="Runs table not initialized")
        raise

    if run_row is None:
        raise HTTPException(status_code=500, detail="Failed to create run")

    # Touch the Task (and reopen "done" tasks) to keep ordering/grouping sensible.
    try:
        if has_intent_key:
            touch_stmt = text(
                "update public.task "
                "set last_touched_at = now(), status = (case when status = 'done' then 'open' else status end) "
                "where id = :task_id "
                "returning "
                "id, title, workflow_key, intent_key, goal, acceptance_criteria, systems_touched, "
                "risk_level, status, created_at, last_touched_at"
            )
        else:
            touch_stmt = text(
                "update public.task "
                "set last_touched_at = now(), status = (case when status = 'done' then 'open' else status end) "
                "where id = :task_id "
                "returning "
                "id, title, workflow_key, goal, acceptance_criteria, systems_touched, "
                "risk_level, status, created_at, last_touched_at"
            )
        touched = (
            session.connection().execute(touch_stmt, {"task_id": task_id}).mappings().first()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=501, detail="Tasks table not initialized")
        raise

    session.commit()

    task_public = TaskPublic(**dict(touched or task_row))
    run_public = RunPublic(**dict(run_row))
    return RunStartPublic(task=task_public, run=run_public, reused_task=reused_task)


@router.get("/{run_id}", response_model=RunPublic)
def read_run(session: SessionDep, current_user: CurrentUser, run_id: uuid.UUID) -> Any:
    """
    Get a Run by ID.
    """

    try:
        stmt = text(
            "select "
            "r.id, r.task_id, r.targets, r.started_at, r.ended_at, r.status, r.summary "
            "from public.run r "
            "where r.id = :run_id "
            "limit 1"
        )
        row = session.connection().execute(stmt, {"run_id": run_id}).mappings().first()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Run not found")
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunPublic(**dict(row))


@router.patch("/{run_id}", response_model=RunPublic)
def update_run(
    session: SessionDep,
    current_user: CurrentUser,
    run_id: uuid.UUID,
    run_in: RunUpdate,
) -> Any:
    """
    Update a Run.
    """

    update = run_in.model_dump(exclude_unset=True)
    if not update:
        raise HTTPException(status_code=422, detail="No fields to update")

    clauses: list[str] = []
    params: dict[str, Any] = {"run_id": run_id}

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

    # Convenience: if status is being set to a terminal state and ended_at wasn't explicitly set, set it.
    if "status" in update and "ended_at" not in update:
        s = update.get("status")
        if isinstance(s, str) and s.strip().lower() in {"done", "aborted", "failed", "success", "error"}:
            clauses.append("ended_at = coalesce(ended_at, now())")

    if not clauses:
        raise HTTPException(status_code=422, detail="No valid fields to update")

    try:
        stmt = text(
            "update public.run "
            f"set {', '.join(clauses)} "
            "where id = :run_id "
            "returning id, task_id, targets, started_at, ended_at, status, summary"
        )
        row = session.connection().execute(stmt, params).mappings().first()
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Run not found")
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunPublic(**dict(row))


@router.delete("/{run_id}", response_model=Message)
def delete_run(session: SessionDep, current_user: CurrentUser, run_id: uuid.UUID) -> Any:
    """
    Delete a Run.

    Note: restricted to superusers; deleting runs removes audit trail for that run.
    """

    get_current_active_superuser(current_user)
    try:
        stmt = text("delete from public.run where id = :run_id returning id")
        deleted = session.connection().execute(stmt, {"run_id": run_id}).first()
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Run not found")
        raise

    if deleted is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return Message(message="Run deleted successfully")


@router.get("/{run_id}/events", response_model=RunEventsPublic)
def read_run_events(
    session: SessionDep,
    current_user: CurrentUser,
    run_id: uuid.UUID,
    skip: int = 0,
    limit: int = 1000,
) -> Any:
    """
    Retrieve Run events.
    """

    try:
        count_stmt = text("select count(*) from public.run_event e where e.run_id = :run_id")
        count = (
            session.connection()
            .execute(count_stmt, {"run_id": run_id})
            .scalar_one()
        )
        stmt = text(
            "select e.id, e.run_id, e.ts, e.type, e.message, e.data, e.supersedes_event_id "
            "from public.run_event e "
            "where e.run_id = :run_id "
            "order by e.ts asc nulls last, e.id asc "
            "offset :skip limit :limit"
        )
        rows = (
            session.connection()
            .execute(stmt, {"run_id": run_id, "skip": skip, "limit": limit})
            .mappings()
            .all()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return RunEventsPublic(data=[], count=0)
        raise

    events = [RunEventPublic(**dict(row)) for row in rows]
    return RunEventsPublic(data=events, count=count)


@router.post("/{run_id}/events", response_model=RunEventPublic, status_code=201)
def create_run_event(
    session: SessionDep,
    current_user: CurrentUser,
    run_id: uuid.UUID,
    event_in: RunEventCreate,
) -> Any:
    """
    Append a Run event (audit log).
    """

    type_ = event_in.type.strip()
    if not type_:
        raise HTTPException(status_code=422, detail="type must not be empty")

    payload = event_in.data or {}
    message = event_in.message.strip() if isinstance(event_in.message, str) and event_in.message.strip() else None
    supersedes_event_id = event_in.supersedes_event_id

    try:
        # Fail cleanly on missing run instead of bubbling FK violations.
        exists = session.connection().execute(
            text("select 1 from public.run r where r.id = :run_id limit 1"),
            {"run_id": run_id},
        ).first()
        if exists is None:
            raise HTTPException(status_code=404, detail="Run not found")

        stmt = text(
            "insert into public.run_event (run_id, ts, type, message, data, supersedes_event_id) "
            "values (:run_id, coalesce(:ts, now()), :type, :message, cast(:data as jsonb), :supersedes_event_id) "
            "returning id, run_id, ts, type, message, data, supersedes_event_id"
        )
        row = (
            session.connection()
            .execute(
                stmt,
                {
                    "run_id": run_id,
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
        session.commit()
    except IntegrityError:
        # Covers bad supersedes_event_id foreign key, etc.
        raise HTTPException(status_code=409, detail="Invalid run event linkage")
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Run not found")
        raise

    if row is None:
        raise HTTPException(status_code=500, detail="Failed to create run event")
    return RunEventPublic(**dict(row))


@router.post("/{run_id}/events/{event_id}/supersede", response_model=RunEventPublic, status_code=201)
def supersede_run_event(
    session: SessionDep,
    current_user: CurrentUser,
    run_id: uuid.UUID,
    event_id: int,
    event_in: RunEventCreate,
) -> Any:
    """
    "Update" a Run event by creating a new event that supersedes it.
    """

    # Ensure the superseded event exists for this run.
    try:
        existing = (
            session.connection()
            .execute(
                text(
                    "select 1 from public.run_event e where e.id = :event_id and e.run_id = :run_id limit 1"
                ),
                {"event_id": event_id, "run_id": run_id},
            )
            .first()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Run event not found")
        raise

    if existing is None:
        raise HTTPException(status_code=404, detail="Run event not found")

    # Force supersedes_event_id to the target event.
    patched = RunEventCreate(
        ts=event_in.ts,
        type=event_in.type,
        message=event_in.message,
        data=event_in.data,
        supersedes_event_id=event_id,
    )
    return create_run_event(session=session, current_user=current_user, run_id=run_id, event_in=patched)


@router.delete("/{run_id}/events/{event_id}", response_model=Message)
def delete_run_event(
    session: SessionDep,
    current_user: CurrentUser,
    run_id: uuid.UUID,
    event_id: int,
) -> Any:
    """
    Delete a Run event.

    Note: restricted to superusers; prefer superseding events instead of deleting.
    """

    get_current_active_superuser(current_user)
    try:
        stmt = text(
            "delete from public.run_event "
            "where id = :event_id and run_id = :run_id "
            "returning id"
        )
        deleted = (
            session.connection()
            .execute(stmt, {"event_id": event_id, "run_id": run_id})
            .first()
        )
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Run event not found")
        raise

    if deleted is None:
        raise HTTPException(status_code=404, detail="Run event not found")
    return Message(message="Run event deleted successfully")


@router.get("/{run_id}/memory-links", response_model=RunMemoryLinksPublic)
def read_run_memory_links(
    session: SessionDep,
    current_user: CurrentUser,
    run_id: uuid.UUID,
    skip: int = 0,
    limit: int = 1000,
) -> Any:
    """
    Retrieve memory links for a Run.
    """

    try:
        count_stmt = text("select count(*) from public.run_library_link l where l.run_id = :run_id")
        count = session.connection().execute(count_stmt, {"run_id": run_id}).scalar_one()

        stmt = text(
            "select "
            "l.relation as relation, "
            "l.created_at as created_at, "
            "li.id as library_item_id, "
            "li.workflow_key as workflow_key, "
            "li.kind as kind, "
            "li.title as title, "
            "li.body_mdc as body_mdc, "
            "li.tags as tags, "
            "li.source_refs as source_refs, "
            "li.promotion_mode as promotion_mode, "
            "li.created_at as library_created_at, "
            "li.last_used_at as last_used_at, "
            "li.superseded_by_id as superseded_by_id "
            "from public.run_library_link l "
            "join public.library_item li on li.id = l.library_item_id "
            "where l.run_id = :run_id "
            "order by l.relation asc, l.created_at desc "
            "offset :skip limit :limit"
        )
        rows = (
            session.connection()
            .execute(stmt, {"run_id": run_id, "skip": skip, "limit": limit})
            .mappings()
            .all()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return RunMemoryLinksPublic(data=[], count=0)
        raise

    links: list[RunMemoryLinkPublic] = []
    for row in rows:
        library_item = LibraryItemPublic(
            id=row["library_item_id"],
            workflow_key=row["workflow_key"],
            kind=row["kind"],
            title=row["title"],
            body_mdc=row["body_mdc"],
            tags=row.get("tags") or {},
            source_refs=row.get("source_refs") or [],
            promotion_mode=row["promotion_mode"],
            created_at=row["library_created_at"],
            last_used_at=row["last_used_at"],
            superseded_by_id=row["superseded_by_id"],
        )
        links.append(
            RunMemoryLinkPublic(
                relation=row["relation"],
                created_at=row["created_at"],
                library_item=library_item,
            )
        )

    return RunMemoryLinksPublic(data=links, count=count)


@router.post("/{run_id}/memory-links", response_model=RunMemoryLinkPublic, status_code=201)
def create_run_memory_link(
    session: SessionDep,
    current_user: CurrentUser,
    run_id: uuid.UUID,
    link_in: RunMemoryLinkCreate,
) -> Any:
    """
    Create a memory link (run_library_link) for a Run.
    """

    created_at = link_in.created_at
    relation = link_in.relation
    library_item_id = link_in.library_item_id

    try:
        exists = session.connection().execute(
            text("select 1 from public.run r where r.id = :run_id limit 1"),
            {"run_id": run_id},
        ).first()
        if exists is None:
            raise HTTPException(status_code=404, detail="Run not found")

        li_exists = session.connection().execute(
            text("select 1 from public.library_item li where li.id = :id limit 1"),
            {"id": library_item_id},
        ).first()
        if li_exists is None:
            raise HTTPException(status_code=404, detail="Library item not found")

        stmt = text(
            "insert into public.run_library_link (run_id, library_item_id, relation, created_at) "
            "values (:run_id, :library_item_id, :relation, coalesce(:created_at, now())) "
            "on conflict (run_id, library_item_id, relation) do update set "
            "created_at = least(public.run_library_link.created_at, excluded.created_at)"
        )
        session.connection().execute(
            stmt,
            {
                "run_id": run_id,
                "library_item_id": library_item_id,
                "relation": relation,
                "created_at": created_at,
            },
        )

        if relation == "used":
            session.connection().execute(
                text("update public.library_item set last_used_at = now() where id = :id"),
                {"id": library_item_id},
            )

        row_stmt = text(
            "select "
            "l.relation as relation, "
            "l.created_at as created_at, "
            "li.id as library_item_id, "
            "li.workflow_key as workflow_key, "
            "li.kind as kind, "
            "li.title as title, "
            "li.body_mdc as body_mdc, "
            "li.tags as tags, "
            "li.source_refs as source_refs, "
            "li.promotion_mode as promotion_mode, "
            "li.created_at as library_created_at, "
            "li.last_used_at as last_used_at, "
            "li.superseded_by_id as superseded_by_id "
            "from public.run_library_link l "
            "join public.library_item li on li.id = l.library_item_id "
            "where l.run_id = :run_id and l.library_item_id = :library_item_id and l.relation = :relation "
            "limit 1"
        )
        row = (
            session.connection()
            .execute(
                row_stmt,
                {"run_id": run_id, "library_item_id": library_item_id, "relation": relation},
            )
            .mappings()
            .first()
        )
        session.commit()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Invalid memory link")
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Run not found")
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="Memory link not created")

    library_item = LibraryItemPublic(
        id=row["library_item_id"],
        workflow_key=row["workflow_key"],
        kind=row["kind"],
        title=row["title"],
        body_mdc=row["body_mdc"],
        tags=row.get("tags") or {},
        source_refs=row.get("source_refs") or [],
        promotion_mode=row["promotion_mode"],
        created_at=row["library_created_at"],
        last_used_at=row["last_used_at"],
        superseded_by_id=row["superseded_by_id"],
    )
    return RunMemoryLinkPublic(
        relation=row["relation"],
        created_at=row["created_at"],
        library_item=library_item,
    )


@router.delete("/{run_id}/memory-links/{library_item_id}", response_model=Message)
def delete_run_memory_link(
    session: SessionDep,
    current_user: CurrentUser,
    run_id: uuid.UUID,
    library_item_id: uuid.UUID,
    relation: str,
) -> Any:
    """
    Delete a memory link (run_library_link).

    Note: restricted to superusers; deleting links harms auditability.
    """

    get_current_active_superuser(current_user)
    relation = relation.strip()
    if not relation:
        raise HTTPException(status_code=422, detail="relation must not be empty")

    try:
        stmt = text(
            "delete from public.run_library_link "
            "where run_id = :run_id and library_item_id = :library_item_id and relation = :relation "
            "returning 1"
        )
        deleted = (
            session.connection()
            .execute(
                stmt,
                {"run_id": run_id, "library_item_id": library_item_id, "relation": relation},
            )
            .first()
        )
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Memory link not found")
        raise

    if deleted is None:
        raise HTTPException(status_code=404, detail="Memory link not found")
    return Message(message="Memory link deleted successfully")


@router.get("/{run_id}/detail", response_model=RunDetailPublic)
def read_run_detail(session: SessionDep, current_user: CurrentUser, run_id: uuid.UUID) -> Any:
    """
    Retrieve a Run, its append-only events, and its memory links (Used/Created/Promoted/Superseded).
    """

    try:
        run_stmt = text(
            "select "
            "r.id, r.task_id, r.targets, r.started_at, r.ended_at, r.status, r.summary "
            "from public.run r "
            "where r.id = :run_id "
            "limit 1"
        )
        run_row = session.connection().execute(run_stmt, {"run_id": run_id}).mappings().first()
        if run_row is None:
            raise HTTPException(status_code=404, detail="Run not found")

        events_stmt = text(
            "select "
            "e.id, e.run_id, e.ts, e.type, e.message, e.data, e.supersedes_event_id "
            "from public.run_event e "
            "where e.run_id = :run_id "
            "order by e.ts asc nulls last, e.id asc"
        )
        event_rows = session.connection().execute(events_stmt, {"run_id": run_id}).mappings().all()

        links_stmt = text(
            "select "
            "l.relation as relation, "
            "l.created_at as created_at, "
            "li.id as library_item_id, "
            "li.workflow_key as workflow_key, "
            "li.kind as kind, "
            "li.title as title, "
            "li.body_mdc as body_mdc, "
            "li.tags as tags, "
            "li.source_refs as source_refs, "
            "li.promotion_mode as promotion_mode, "
            "li.created_at as library_created_at, "
            "li.last_used_at as last_used_at, "
            "li.superseded_by_id as superseded_by_id "
            "from public.run_library_link l "
            "join public.library_item li on li.id = l.library_item_id "
            "where l.run_id = :run_id "
            "order by l.relation asc, l.created_at desc"
        )
        link_rows = session.connection().execute(links_stmt, {"run_id": run_id}).mappings().all()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Run not found")
        raise

    run = RunPublic(**dict(run_row))
    events = [RunEventPublic(**dict(row)) for row in event_rows]

    links: list[RunMemoryLinkPublic] = []
    for row in link_rows:
        library_item = LibraryItemPublic(
            id=row["library_item_id"],
            workflow_key=row["workflow_key"],
            kind=row["kind"],
            title=row["title"],
            body_mdc=row["body_mdc"],
            tags=row.get("tags") or {},
            source_refs=row.get("source_refs") or [],
            promotion_mode=row["promotion_mode"],
            created_at=row["library_created_at"],
            last_used_at=row["last_used_at"],
            superseded_by_id=row["superseded_by_id"],
        )
        links.append(
            RunMemoryLinkPublic(
                relation=row["relation"],
                created_at=row["created_at"],
                library_item=library_item,
            )
        )

    return RunDetailPublic(run=run, events=events, memory_links=links)
