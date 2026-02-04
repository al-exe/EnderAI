import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import or_
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.models import (
    LibraryItem,
    LibraryItemKind,
    LibraryItemCreate,
    LibraryItemPublic,
    LibraryItemsPublic,
    LibraryItemUpdate,
)

router = APIRouter(prefix="/library", tags=["library"])


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
        filters.append(or_(LibraryItem.title.ilike(like), LibraryItem.body_mdc.ilike(like)))

    count_statement = select(func.count()).select_from(LibraryItem)
    if filters:
        count_statement = count_statement.where(*filters)
    count = session.exec(count_statement).one()

    statement = select(LibraryItem).order_by(LibraryItem.created_at.desc()).offset(skip).limit(limit)
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

    existing.superseded_by_id = new_item.id
    session.add(new_item)
    session.add(existing)
    session.commit()
    session.refresh(new_item)
    return new_item
