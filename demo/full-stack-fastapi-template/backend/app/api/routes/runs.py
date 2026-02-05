import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    LibraryItemPublic,
    RunDetailPublic,
    RunEventPublic,
    RunMemoryLinkPublic,
    RunPublic,
)

router = APIRouter(prefix="/runs", tags=["runs"])


def _is_missing_table_error(err: Exception) -> bool:
    message = str(err).lower()
    return "does not exist" in message and "relation" in message


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

