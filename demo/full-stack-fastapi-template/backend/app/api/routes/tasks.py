import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.models import (
    ExecutionPublic,
    ExecutionsPublic,
    Message,
    ThreadCreate,
    ThreadPublic,
    ThreadsPublic,
    ThreadUpdate,
)

router = APIRouter(prefix="/threads", tags=["threads"])


def _is_missing_table_error(err: Exception) -> bool:
    message = str(err).lower()
    return "does not exist" in message and "relation" in message


def _thread_has_intent_key_column(session: SessionDep) -> bool:
    # Use information_schema to keep the API backward-compatible with older DB schemas.
    stmt = text(
        "select 1 "
        "from information_schema.columns "
        "where table_schema = 'public' and table_name = 'thread' and column_name = 'intent_key' "
        "limit 1"
    )
    return session.connection().execute(stmt).first() is not None


@router.get("/", response_model=ThreadsPublic)
def read_threads(
    session: SessionDep,
    current_user: CurrentUser,
    workflow_key: str | None = None,
    intent_key: str | None = None,
    status: str | None = None,
    q: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve Threads (DB-backed memory).
    """

    workflow_key = workflow_key.strip() if workflow_key else None
    intent_key = intent_key.strip() if intent_key else None
    status = status.strip() if status else None
    q = q.strip() if q else None

    has_intent_key = _thread_has_intent_key_column(session)
    if intent_key and not has_intent_key:
        raise HTTPException(
            status_code=501,
            detail="Threads table missing intent_key column; run scripts/create_memory_tables.py to upgrade schema",
        )

    clauses: list[str] = []
    params: dict[str, Any] = {"skip": skip, "limit": limit}

    if workflow_key:
        clauses.append("t.workflow_key = :workflow_key")
        params["workflow_key"] = workflow_key
    if intent_key:
        clauses.append("t.intent_key = :intent_key")
        params["intent_key"] = intent_key
    if status:
        clauses.append("t.status = :status")
        params["status"] = status
    if q:
        q_fields = [
            "t.title ilike :q",
            "t.goal ilike :q",
            "t.acceptance_criteria ilike :q",
            "t.workflow_key ilike :q",
        ]
        if has_intent_key:
            q_fields.insert(1, "t.intent_key ilike :q")
        clauses.append(
            "(" + " or ".join(q_fields) + ")"
        )
        params["q"] = f"%{q}%"

    where_sql = f" where {' and '.join(clauses)}" if clauses else ""

    try:
        count_stmt = text(f"select count(*) from public.thread t{where_sql}")
        count = session.connection().execute(count_stmt, params).scalar_one()

        data_stmt = text(
            "select "
            "t.id, t.title, t.workflow_key, "
            + ("t.intent_key, " if has_intent_key else "")
            + "t.goal, t.acceptance_criteria, "
            "t.systems_touched, t.risk_level, t.status, t.created_at, t.last_touched_at "
            "from public.thread t"
            f"{where_sql} "
            "order by t.last_touched_at desc nulls last "
            "offset :skip limit :limit"
        )
        rows = session.connection().execute(data_stmt, params).mappings().all()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return ThreadsPublic(data=[], count=0)
        raise

    threads = [ThreadPublic(**dict(row)) for row in rows]
    return ThreadsPublic(data=threads, count=count)


@router.post("/", response_model=ThreadPublic, status_code=201)
def create_thread(session: SessionDep, current_user: CurrentUser, thread_in: ThreadCreate) -> Any:
    """
    Create a Thread (DB-backed memory).
    """

    title = thread_in.title.strip()
    workflow_key = thread_in.workflow_key.strip()
    intent_key = (
        thread_in.intent_key.strip()
        if isinstance(thread_in.intent_key, str) and thread_in.intent_key.strip()
        else None
    )

    if not title:
        raise HTTPException(status_code=422, detail="Title must not be empty")
    if not workflow_key:
        raise HTTPException(status_code=422, detail="workflow_key must not be empty")

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

    has_intent_key = _thread_has_intent_key_column(session)
    if intent_key and not has_intent_key:
        raise HTTPException(
            status_code=501,
            detail="Threads table missing intent_key column; run scripts/create_memory_tables.py to upgrade schema",
        )

    try:
        if has_intent_key:
            stmt = text(
                "insert into public.thread ("
                "id, title, workflow_key, intent_key, goal, acceptance_criteria, systems_touched, risk_level, status"
                ") values ("
                ":id, :title, :workflow_key, :intent_key, :goal, :acceptance_criteria, cast(:systems_touched as jsonb), :risk_level, :status"
                ") returning "
                "id, title, workflow_key, intent_key, goal, acceptance_criteria, systems_touched, "
                "risk_level, status, created_at, last_touched_at"
            )
        else:
            stmt = text(
                "insert into public.thread ("
                "id, title, workflow_key, goal, acceptance_criteria, systems_touched, risk_level, status"
                ") values ("
                ":id, :title, :workflow_key, :goal, :acceptance_criteria, cast(:systems_touched as jsonb), :risk_level, :status"
                ") returning "
                "id, title, workflow_key, goal, acceptance_criteria, systems_touched, "
                "risk_level, status, created_at, last_touched_at"
            )
        row = (
            session.connection()
            .execute(
                stmt,
                (
                    {
                        "id": thread_id,
                        "title": title,
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
                        "title": title,
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
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=501, detail="Threads table not initialized")
        raise

    if row is None:
        raise HTTPException(status_code=500, detail="Failed to create thread")
    return ThreadPublic(**dict(row))


@router.get("/{thread_id}", response_model=ThreadPublic)
def read_thread(session: SessionDep, current_user: CurrentUser, thread_id: uuid.UUID) -> Any:
    """
    Get a Thread by ID.
    """

    has_intent_key = _thread_has_intent_key_column(session)

    try:
        stmt = text(
            "select "
            "t.id, t.title, t.workflow_key, "
            + ("t.intent_key, " if has_intent_key else "")
            + "t.goal, t.acceptance_criteria, "
            "t.systems_touched, t.risk_level, t.status, t.created_at, t.last_touched_at "
            "from public.thread t "
            "where t.id = :thread_id "
            "limit 1"
        )
        row = session.connection().execute(stmt, {"thread_id": thread_id}).mappings().first()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Thread not found")
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return ThreadPublic(**dict(row))


@router.get("/{thread_id}/executions", response_model=ExecutionsPublic)
def read_thread_executions(
    session: SessionDep,
    current_user: CurrentUser,
    thread_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve Executions for a Thread.
    """

    try:
        count_stmt = text("select count(*) from public.execution r where r.thread_id = :thread_id")
        count = session.connection().execute(count_stmt, {"thread_id": thread_id}).scalar_one()

        stmt = text(
            "select "
            "r.id, r.thread_id, r.targets, r.started_at, r.ended_at, r.status, r.summary "
            "from public.execution r "
            "where r.thread_id = :thread_id "
            "order by r.started_at desc nulls last "
            "offset :skip limit :limit"
        )
        rows = (
            session.connection()
            .execute(stmt, {"thread_id": thread_id, "skip": skip, "limit": limit})
            .mappings()
            .all()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return ExecutionsPublic(data=[], count=0)
        raise

    executions = [ExecutionPublic(**dict(row)) for row in rows]
    return ExecutionsPublic(data=executions, count=count)


@router.patch("/{thread_id}", response_model=ThreadPublic)
def update_thread(
    session: SessionDep,
    current_user: CurrentUser,
    thread_id: uuid.UUID,
    thread_in: ThreadUpdate,
) -> Any:
    """
    Update a Thread (DB-backed memory).
    """

    has_intent_key = _thread_has_intent_key_column(session)
    update = thread_in.model_dump(exclude_unset=True)
    if not update:
        raise HTTPException(status_code=422, detail="No fields to update")

    if "intent_key" in update and update.get("intent_key") is not None and not has_intent_key:
        raise HTTPException(
            status_code=501,
            detail="Threads table missing intent_key column; run scripts/create_memory_tables.py to upgrade schema",
        )

    clauses: list[str] = []
    params: dict[str, Any] = {"thread_id": thread_id}

    if "title" in update:
        title = update.get("title")
        if title is None:
            # Allow explicit null to mean "no change" for clients that send it.
            pass
        else:
            title = title.strip()
            if not title:
                raise HTTPException(status_code=422, detail="Title must not be empty")
            clauses.append("title = :title")
            params["title"] = title

    if "workflow_key" in update:
        workflow_key = update.get("workflow_key")
        if workflow_key is None:
            pass
        else:
            workflow_key = workflow_key.strip()
            if not workflow_key:
                raise HTTPException(status_code=422, detail="workflow_key must not be empty")
            clauses.append("workflow_key = :workflow_key")
            params["workflow_key"] = workflow_key

    if has_intent_key and "intent_key" in update:
        intent_key = update.get("intent_key")
        if intent_key is None:
            clauses.append("intent_key = null")
        else:
            intent_key = intent_key.strip()
            if not intent_key:
                raise HTTPException(status_code=422, detail="intent_key must not be empty")
            clauses.append("intent_key = :intent_key")
            params["intent_key"] = intent_key

    if "goal" in update:
        goal = update.get("goal")
        if isinstance(goal, str):
            goal = goal.strip() or None
        clauses.append("goal = :goal")
        params["goal"] = goal

    if "acceptance_criteria" in update:
        acceptance_criteria = update.get("acceptance_criteria")
        if isinstance(acceptance_criteria, str):
            acceptance_criteria = acceptance_criteria.strip() or None
        clauses.append("acceptance_criteria = :acceptance_criteria")
        params["acceptance_criteria"] = acceptance_criteria

    if "systems_touched" in update:
        systems_touched = update.get("systems_touched")
        clauses.append("systems_touched = cast(:systems_touched as jsonb)")
        params["systems_touched"] = json.dumps(systems_touched or {})

    if "risk_level" in update:
        risk_level = update.get("risk_level")
        if risk_level is None:
            pass
        else:
            risk_level = risk_level.strip()
            if not risk_level:
                raise HTTPException(status_code=422, detail="risk_level must not be empty")
            clauses.append("risk_level = :risk_level")
            params["risk_level"] = risk_level

    if "status" in update:
        status = update.get("status")
        if status is None:
            pass
        else:
            status = status.strip()
            if not status:
                raise HTTPException(status_code=422, detail="status must not be empty")
            clauses.append("status = :status")
            params["status"] = status

    if not clauses:
        raise HTTPException(status_code=422, detail="No valid fields to update")

    try:
        stmt = text(
            "update public.thread "
            f"set {', '.join(clauses)}, last_touched_at = now() "
            "where id = :thread_id "
            "returning "
            "id, title, workflow_key, "
            + ("intent_key, " if has_intent_key else "")
            + "goal, acceptance_criteria, "
            "systems_touched, risk_level, status, created_at, last_touched_at"
        )
        row = (
            session.connection()
            .execute(stmt, params)
            .mappings()
            .first()
        )
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Thread not found")
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return ThreadPublic(**dict(row))


@router.delete("/{thread_id}", response_model=Message)
def delete_thread(session: SessionDep, current_user: CurrentUser, thread_id: uuid.UUID) -> Any:
    """
    Delete a Thread.

    Note: this is intentionally restricted to superusers; deleting threads cascades to Executions/Events/Links.
    """

    get_current_active_superuser(current_user)
    try:
        stmt = text("delete from public.thread where id = :thread_id returning id")
        deleted = session.connection().execute(stmt, {"thread_id": thread_id}).first()
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Thread not found")
        raise

    if deleted is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return Message(message="Thread deleted successfully")
