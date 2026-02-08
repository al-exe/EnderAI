import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.api.deps import CurrentUser, SessionDep
from app.models import RunPublic, RunsPublic, TaskCreate, TaskPublic, TasksPublic, TaskTitleUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _is_missing_table_error(err: Exception) -> bool:
    message = str(err).lower()
    return "does not exist" in message and "relation" in message


@router.get("/", response_model=TasksPublic)
def read_tasks(
    session: SessionDep,
    current_user: CurrentUser,
    workflow_key: str | None = None,
    status: str | None = None,
    q: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve Tasks (DB-backed memory).
    """

    workflow_key = workflow_key.strip() if workflow_key else None
    status = status.strip() if status else None
    q = q.strip() if q else None

    clauses: list[str] = []
    params: dict[str, Any] = {"skip": skip, "limit": limit}

    if workflow_key:
        clauses.append("t.workflow_key = :workflow_key")
        params["workflow_key"] = workflow_key
    if status:
        clauses.append("t.status = :status")
        params["status"] = status
    if q:
        clauses.append(
            "("
            "t.title ilike :q or "
            "t.goal ilike :q or "
            "t.acceptance_criteria ilike :q or "
            "t.workflow_key ilike :q"
            ")"
        )
        params["q"] = f"%{q}%"

    where_sql = f" where {' and '.join(clauses)}" if clauses else ""

    try:
        count_stmt = text(f"select count(*) from public.task t{where_sql}")
        count = session.connection().execute(count_stmt, params).scalar_one()

        data_stmt = text(
            "select "
            "t.id, t.title, t.workflow_key, t.goal, t.acceptance_criteria, "
            "t.systems_touched, t.risk_level, t.status, t.created_at, t.last_touched_at "
            "from public.task t"
            f"{where_sql} "
            "order by t.last_touched_at desc nulls last "
            "offset :skip limit :limit"
        )
        rows = session.connection().execute(data_stmt, params).mappings().all()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return TasksPublic(data=[], count=0)
        raise

    tasks = [TaskPublic(**dict(row)) for row in rows]
    return TasksPublic(data=tasks, count=count)


@router.post("/", response_model=TaskPublic, status_code=201)
def create_task(session: SessionDep, current_user: CurrentUser, task_in: TaskCreate) -> Any:
    """
    Create a Task (DB-backed memory).
    """

    title = task_in.title.strip()
    workflow_key = task_in.workflow_key.strip()

    if not title:
        raise HTTPException(status_code=422, detail="Title must not be empty")
    if not workflow_key:
        raise HTTPException(status_code=422, detail="workflow_key must not be empty")

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
        stmt = text(
            "insert into public.task ("
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
                {
                    "id": task_id,
                    "title": title,
                    "workflow_key": workflow_key,
                    "goal": goal,
                    "acceptance_criteria": acceptance_criteria,
                    "systems_touched": json.dumps(systems_touched),
                    "risk_level": risk_level,
                    "status": status,
                },
            )
            .mappings()
            .first()
        )
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=501, detail="Tasks table not initialized")
        raise

    if row is None:
        raise HTTPException(status_code=500, detail="Failed to create task")
    return TaskPublic(**dict(row))


@router.get("/{task_id}", response_model=TaskPublic)
def read_task(session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID) -> Any:
    """
    Get a Task by ID.
    """

    try:
        stmt = text(
            "select "
            "t.id, t.title, t.workflow_key, t.goal, t.acceptance_criteria, "
            "t.systems_touched, t.risk_level, t.status, t.created_at, t.last_touched_at "
            "from public.task t "
            "where t.id = :task_id "
            "limit 1"
        )
        row = session.connection().execute(stmt, {"task_id": task_id}).mappings().first()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Task not found")
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskPublic(**dict(row))


@router.get("/{task_id}/runs", response_model=RunsPublic)
def read_task_runs(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve Runs for a Task.
    """

    try:
        count_stmt = text("select count(*) from public.run r where r.task_id = :task_id")
        count = session.connection().execute(count_stmt, {"task_id": task_id}).scalar_one()

        stmt = text(
            "select "
            "r.id, r.task_id, r.targets, r.started_at, r.ended_at, r.status, r.summary "
            "from public.run r "
            "where r.task_id = :task_id "
            "order by r.started_at desc nulls last "
            "offset :skip limit :limit"
        )
        rows = (
            session.connection()
            .execute(stmt, {"task_id": task_id, "skip": skip, "limit": limit})
            .mappings()
            .all()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return RunsPublic(data=[], count=0)
        raise

    runs = [RunPublic(**dict(row)) for row in rows]
    return RunsPublic(data=runs, count=count)


@router.patch("/{task_id}", response_model=TaskPublic)
def update_task_title(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    task_in: TaskTitleUpdate,
) -> Any:
    """
    Update a Task title (DB-backed memory).
    """

    title = task_in.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title must not be empty")

    try:
        stmt = text(
            "update public.task "
            "set title = :title, last_touched_at = now() "
            "where id = :task_id "
            "returning "
            "id, title, workflow_key, goal, acceptance_criteria, "
            "systems_touched, risk_level, status, created_at, last_touched_at"
        )
        row = (
            session.connection()
            .execute(stmt, {"task_id": task_id, "title": title})
            .mappings()
            .first()
        )
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Task not found")
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskPublic(**dict(row))
