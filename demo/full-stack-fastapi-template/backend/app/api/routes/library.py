import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import ProgrammingError
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.models import (
    LibraryItem,
    LibraryItemKind,
    LibraryItemCreate,
    LibraryItemPublic,
    LibraryItemsPublic,
    LibraryItemUpdate,
    Message,
    WorkflowBucket,
    WorkflowKeyCount,
    WorkflowKeysPublic,
)

router = APIRouter(prefix="/library", tags=["library"])


def _is_missing_table_error(err: Exception) -> bool:
    message = str(err).lower()
    return "does not exist" in message and "relation" in message


def _humanize_workflow_key(workflow_key: str) -> str:
    parts = workflow_key.strip().split("_")
    words: list[str] = []
    for part in parts:
        lower = part.lower()
        if lower == "github":
            words.append("GitHub")
        elif lower == "api":
            words.append("API")
        elif lower == "db":
            words.append("DB")
        else:
            words.append(part.capitalize())
    return " ".join(words) if words else workflow_key


@router.get("/workflow-keys", response_model=WorkflowKeysPublic)
def read_library_workflow_keys(
    session: SessionDep,
    current_user: CurrentUser,
    current_only: bool = True,
) -> Any:
    """
    Retrieve distinct library workflow keys ("buckets") with counts.
    """

    statement = select(
        LibraryItem.workflow_key,
        WorkflowBucket.bucket_name,
        func.count(LibraryItem.id),
    ).select_from(LibraryItem)
    statement = statement.outerjoin(
        WorkflowBucket,
        WorkflowBucket.workflow_key == LibraryItem.workflow_key,
    )
    statement = statement.group_by(LibraryItem.workflow_key, WorkflowBucket.bucket_name)
    statement = statement.order_by(func.count(LibraryItem.id).desc())
    if current_only:
        statement = statement.where(LibraryItem.superseded_by_id.is_(None))

    rows = session.exec(statement).all()
    data = [
        WorkflowKeyCount(
            workflow_key=row[0],
            bucket_name=row[1] or _humanize_workflow_key(row[0]),
            count=row[2],
        )
        for row in rows
    ]
    return WorkflowKeysPublic(data=data)


@router.get("/", response_model=LibraryItemsPublic)
def read_library_items(
    session: SessionDep,
    current_user: CurrentUser,
    workflow_key: str | None = None,
    kind: LibraryItemKind | None = None,
    q: str | None = None,
    current_only: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve library items.
    """

    filters: list[Any] = []

    if workflow_key:
        filters.append(LibraryItem.workflow_key == workflow_key)
    if kind:
        filters.append(LibraryItem.kind == kind)
    if current_only:
        filters.append(LibraryItem.superseded_by_id.is_(None))
    if q:
        like = f"%{q}%"
        filters.append(
            or_(
                LibraryItem.title.ilike(like),
                LibraryItem.body_mdc.ilike(like),
                LibraryItem.workflow_key.ilike(like),
                WorkflowBucket.bucket_name.ilike(like),
            )
        )

    count_statement = select(func.count()).select_from(LibraryItem)
    if q:
        count_statement = count_statement.outerjoin(
            WorkflowBucket,
            WorkflowBucket.workflow_key == LibraryItem.workflow_key,
        )
    if filters:
        count_statement = count_statement.where(*filters)
    count = session.exec(count_statement).one()

    statement = select(LibraryItem).order_by(LibraryItem.created_at.desc()).offset(skip).limit(limit)
    if q:
        statement = statement.outerjoin(
            WorkflowBucket,
            WorkflowBucket.workflow_key == LibraryItem.workflow_key,
        )
    if filters:
        statement = statement.where(*filters)
    items = session.exec(statement).all()

    return LibraryItemsPublic(data=items, count=count)


@router.get("/{id}", response_model=LibraryItemPublic)
def read_library_item(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
    """
    Get library item by ID.
    """
    item = session.get(LibraryItem, id)
    if not item:
        raise HTTPException(status_code=404, detail="Library item not found")
    return item


@router.post("/", response_model=LibraryItemPublic)
def create_library_item(
    *, session: SessionDep, current_user: CurrentUser, item_in: LibraryItemCreate
) -> Any:
    """
    Create new library item.

    Notes:
    - Deletes are not supported; supersede instead.
    """
    get_current_active_superuser(current_user)
    item = LibraryItem.model_validate(item_in)
    bucket = session.get(WorkflowBucket, item.workflow_key)
    if bucket is None:
        session.add(
            WorkflowBucket(
                workflow_key=item.workflow_key,
                bucket_name=_humanize_workflow_key(item.workflow_key),
            )
        )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.put("/{id}", response_model=LibraryItemPublic)
def update_library_item(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    item_in: LibraryItemUpdate,
) -> Any:
    """
    Update a library item by superseding it.

    This endpoint never edits the existing row; it creates a new row and sets
    `superseded_by_id` on the previous item.
    """
    get_current_active_superuser(current_user)

    existing = session.get(LibraryItem, id)
    if not existing:
        raise HTTPException(status_code=404, detail="Library item not found")
    if existing.superseded_by_id is not None:
        raise HTTPException(status_code=409, detail="Cannot update a superseded library item")

    update = item_in.model_dump(exclude_unset=True)
    new_item = LibraryItem(
        workflow_key=update.get("workflow_key", existing.workflow_key),
        kind=update.get("kind", existing.kind),
        title=update.get("title", existing.title),
        body_mdc=update.get("body_mdc", existing.body_mdc),
        tags=update.get("tags", existing.tags),
        source_refs=update.get("source_refs", existing.source_refs),
        promotion_mode=update.get("promotion_mode", existing.promotion_mode),
        last_used_at=existing.last_used_at,
    )
    bucket = session.get(WorkflowBucket, new_item.workflow_key)
    if bucket is None:
        session.add(
            WorkflowBucket(
                workflow_key=new_item.workflow_key,
                bucket_name=_humanize_workflow_key(new_item.workflow_key),
            )
        )

    existing.superseded_by_id = new_item.id
    session.add(new_item)
    session.add(existing)
    session.commit()
    session.refresh(new_item)
    return new_item


@router.delete("/{id}", response_model=Message)
def delete_library_item(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
    """
    Delete a library item.

    Note: restricted to superusers. Deletion is blocked if the item is referenced.
    Prefer superseding instead of deleting.
    """

    get_current_active_superuser(current_user)
    item = session.get(LibraryItem, id)
    if not item:
        raise HTTPException(status_code=404, detail="Library item not found")

    # Block deletion if referenced by newer versions.
    newer_count = (
        session.exec(
            select(func.count()).select_from(LibraryItem).where(LibraryItem.superseded_by_id == id)
        ).one()
    )
    if newer_count and int(newer_count) > 0:
        raise HTTPException(status_code=409, detail="Library item is referenced by newer versions")

    # Actual check (raw SQL)
    from sqlalchemy import text as sql_text

    linked_count = (
        0
    )
    try:
        linked_count = (
            session.connection()
            .execute(
                sql_text(
                    "select count(*) from public.run_library_link where library_item_id = :id"
                ),
                {"id": id},
            )
            .scalar_one()
        )
    except ProgrammingError as e:
        if not _is_missing_table_error(e):
            raise
    if linked_count and int(linked_count) > 0:
        raise HTTPException(status_code=409, detail="Library item is linked from runs")

    session.delete(item)
    session.commit()
    return Message(message="Library item deleted successfully")
