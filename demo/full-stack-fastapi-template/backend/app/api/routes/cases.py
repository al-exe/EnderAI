import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.api.deps import CurrentUser, SessionDep
from app.core.cases import (
    build_case_public,
    execution_has_column,
    is_terminal_case_status,
    materialize_case_data,
    render_case_hydration,
    render_case_memo,
)
from app.core.topics import refresh_topic_rollup
from app.models import CaseHydrationView, CaseMemoView, CasePublic, CasesPublic, CaseUpdate

router = APIRouter(prefix="/cases", tags=["cases"])


def _is_missing_table_error(err: Exception) -> bool:
    message = str(err).lower()
    return "does not exist" in message and "relation" in message


def _execution_columns_sql(session: SessionDep, alias: str = "e") -> str:
    columns = [
        f"{alias}.id",
        f"{alias}.thread_id",
        f"{alias}.started_at",
        f"{alias}.ended_at",
        f"{alias}.status",
        f"{alias}.summary",
    ]
    if execution_has_column(session, "updated_at"):
        columns.append(f"{alias}.updated_at as updated_at")
    if execution_has_column(session, "case_data"):
        columns.append(f"{alias}.case_data as case_data")
    if execution_has_column(session, "context_pack_snapshot"):
        columns.append(f"{alias}.context_pack_snapshot as context_pack_snapshot")
    return ", ".join(columns)


def _read_case_rows(
    session: SessionDep,
    case_id: uuid.UUID,
) -> tuple[dict[str, Any], dict[str, Any]]:
    execution_stmt = text(
        "select "
        + _execution_columns_sql(session)
        + " from public.execution e where e.id = :case_id limit 1"
    )
    execution_row = (
        session.connection().execute(execution_stmt, {"case_id": case_id}).mappings().first()
    )
    if execution_row is None:
        raise HTTPException(status_code=404, detail="Case not found")

    thread_stmt = text(
        "select t.id, t.title from public.thread t where t.id = :thread_id limit 1"
    )
    thread_row = (
        session.connection()
        .execute(thread_stmt, {"thread_id": execution_row["thread_id"]})
        .mappings()
        .first()
    )
    if thread_row is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return dict(execution_row), dict(thread_row)


@router.get("/", response_model=CasesPublic)
def read_cases(
    session: SessionDep,
    current_user: CurrentUser,
    topic_id: uuid.UUID | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve Cases as compatibility views over Executions.
    """

    clauses: list[str] = []
    params: dict[str, Any] = {"skip": skip, "limit": limit}
    if topic_id is not None:
        clauses.append("e.thread_id = :topic_id")
        params["topic_id"] = topic_id
    if isinstance(status, str) and status.strip():
        clauses.append("e.status = :status")
        params["status"] = status.strip()

    where_sql = f" where {' and '.join(clauses)}" if clauses else ""
    order_column = "coalesce(e.updated_at, e.started_at)" if execution_has_column(session, "updated_at") else "e.started_at"

    try:
        count_stmt = text(
            "select count(*) from public.execution e join public.thread t on t.id = e.thread_id"
            + where_sql
        )
        count = session.connection().execute(count_stmt, params).scalar_one()

        data_stmt = text(
            "select "
            + _execution_columns_sql(session)
            + ", t.id as topic_id, t.title as topic_title "
            "from public.execution e "
            "join public.thread t on t.id = e.thread_id"
            + where_sql
            + f" order by {order_column} desc nulls last offset :skip limit :limit"
        )
        rows = session.connection().execute(data_stmt, params).mappings().all()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return CasesPublic(data=[], count=0)
        raise

    cases = [
        build_case_public(dict(row), {"id": row["topic_id"], "title": row["topic_title"]})
        for row in rows
    ]
    return CasesPublic(data=cases, count=count)


@router.get("/{case_id}", response_model=CasePublic)
def read_case(session: SessionDep, current_user: CurrentUser, case_id: uuid.UUID) -> Any:
    """
    Get a Case compatibility view by ID.
    """

    try:
        execution_row, thread_row = _read_case_rows(session, case_id)
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Case not found")
        raise

    return build_case_public(execution_row, thread_row)


@router.patch("/{case_id}", response_model=CasePublic)
def update_case(
    session: SessionDep,
    current_user: CurrentUser,
    case_id: uuid.UUID,
    case_in: CaseUpdate,
) -> Any:
    """
    Update the canonical structured Case document.
    """

    has_case_data = execution_has_column(session, "case_data")
    has_context_pack_snapshot = execution_has_column(session, "context_pack_snapshot")
    has_updated_at = execution_has_column(session, "updated_at")
    if not has_case_data or not has_context_pack_snapshot:
        raise HTTPException(
            status_code=501,
            detail="Cases require execution.case_data and execution.context_pack_snapshot; run scripts/create_memory_tables.py to upgrade schema",
        )

    update = case_in.model_dump(mode="json", exclude_unset=True)
    if not update:
        raise HTTPException(status_code=422, detail="No fields to update")

    try:
        execution_row, thread_row = _read_case_rows(session, case_id)
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Case not found")
        raise

    current_case = build_case_public(execution_row, thread_row)
    case_data = materialize_case_data(current_case)
    snapshot_payload = current_case.context_pack_snapshot.model_dump(mode="json")

    status_value = None
    if "status" in update and isinstance(update["status"], str):
        status_value = update["status"].strip()
        if not status_value:
            raise HTTPException(status_code=422, detail="status must not be empty")
        update["status"] = status_value

    if "summary_current" in update and isinstance(update["summary_current"], str):
        update["summary_current"] = update["summary_current"].strip() or None
    if "source" in update and isinstance(update["source"], str):
        update["source"] = update["source"].strip() or None
    if "title" in update and isinstance(update["title"], str):
        update["title"] = update["title"].strip()
        if not update["title"]:
            raise HTTPException(status_code=422, detail="title must not be empty")

    if "context_pack_snapshot" in update:
        snapshot_payload = update.pop("context_pack_snapshot") or {}

    execution_summary = current_case.summary_current or current_case.title
    if "summary_current" in update:
        execution_summary = update["summary_current"] or execution_summary

    for key, value in update.items():
        if key == "status":
            continue
        case_data[key] = value

    clauses = [
        "case_data = cast(:case_data as jsonb)",
        "context_pack_snapshot = cast(:context_pack_snapshot as jsonb)",
        "summary = :summary",
    ]
    params: dict[str, Any] = {
        "case_id": case_id,
        "case_data": json.dumps(case_data),
        "context_pack_snapshot": json.dumps(snapshot_payload),
        "summary": execution_summary,
    }

    if status_value is not None:
        clauses.append("status = :status")
        params["status"] = status_value
        if is_terminal_case_status(status_value):
            clauses.append("ended_at = coalesce(ended_at, now())")
        else:
            clauses.append("ended_at = null")

    if has_updated_at:
        clauses.append("updated_at = now()")

    try:
        stmt = text(
            "update public.execution set "
            + ", ".join(clauses)
            + " where id = :case_id returning "
            + _execution_columns_sql(session)
        )
        execution_row = (
            session.connection().execute(stmt, params).mappings().first()
        )
        refresh_topic_rollup(session, thread_row["id"], persist=True)
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Case not found")
        raise

    if execution_row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return build_case_public(dict(execution_row), thread_row)


@router.get("/{case_id}/memo", response_model=CaseMemoView)
def read_case_memo(session: SessionDep, current_user: CurrentUser, case_id: uuid.UUID) -> Any:
    """
    Render the human memo view from the canonical Case record.
    """

    try:
        execution_row, thread_row = _read_case_rows(session, case_id)
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Case not found")
        raise

    case = build_case_public(execution_row, thread_row)
    return render_case_memo(case)


@router.get("/{case_id}/hydration", response_model=CaseHydrationView)
def read_case_hydration(
    session: SessionDep,
    current_user: CurrentUser,
    case_id: uuid.UUID,
) -> Any:
    """
    Render the AI hydration view from the canonical Case record.
    """

    try:
        execution_row, thread_row = _read_case_rows(session, case_id)
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Case not found")
        raise

    case = build_case_public(execution_row, thread_row)
    return render_case_hydration(case)
