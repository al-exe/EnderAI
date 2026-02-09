import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import ProgrammingError
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.models import (
    Artifact,
    ArtifactKind,
    ArtifactCreate,
    ArtifactPublic,
    ArtifactsPublic,
    ArtifactUpdate,
    Message,
    WorkflowBucket,
    WorkflowKeyCount,
    WorkflowKeysPublic,
)

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


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
def read_artifact_workflow_keys(
    session: SessionDep,
    current_user: CurrentUser,
    current_only: bool = True,
) -> Any:
    """
    Retrieve distinct artifact workflow keys ("buckets") with counts.
    """

    statement = select(
        Artifact.workflow_key,
        WorkflowBucket.bucket_name,
        func.count(Artifact.id),
    ).select_from(Artifact)
    statement = statement.outerjoin(
        WorkflowBucket,
        WorkflowBucket.workflow_key == Artifact.workflow_key,
    )
    statement = statement.group_by(Artifact.workflow_key, WorkflowBucket.bucket_name)
    statement = statement.order_by(func.count(Artifact.id).desc())
    if current_only:
        statement = statement.where(Artifact.superseded_by_id.is_(None))

    try:
        rows = session.exec(statement).all()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return WorkflowKeysPublic(data=[])
        raise
    data = [
        WorkflowKeyCount(
            workflow_key=row[0],
            bucket_name=row[1] or _humanize_workflow_key(row[0]),
            count=row[2],
        )
        for row in rows
    ]
    return WorkflowKeysPublic(data=data)


@router.get("/", response_model=ArtifactsPublic)
def read_artifacts(
    session: SessionDep,
    current_user: CurrentUser,
    workflow_key: str | None = None,
    kind: ArtifactKind | None = None,
    q: str | None = None,
    current_only: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve artifacts.
    """

    filters: list[Any] = []

    if workflow_key:
        filters.append(Artifact.workflow_key == workflow_key)
    if kind:
        filters.append(Artifact.kind == kind)
    if current_only:
        filters.append(Artifact.superseded_by_id.is_(None))
    if q:
        like = f"%{q}%"
        filters.append(
            or_(
                Artifact.title.ilike(like),
                Artifact.body_mdc.ilike(like),
                Artifact.workflow_key.ilike(like),
                WorkflowBucket.bucket_name.ilike(like),
            )
        )

    count_statement = select(func.count()).select_from(Artifact)
    if q:
        count_statement = count_statement.outerjoin(
            WorkflowBucket,
            WorkflowBucket.workflow_key == Artifact.workflow_key,
        )
    if filters:
        count_statement = count_statement.where(*filters)
    try:
        count = session.exec(count_statement).one()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return ArtifactsPublic(data=[], count=0)
        raise

    statement = select(Artifact).order_by(Artifact.created_at.desc()).offset(skip).limit(limit)
    if q:
        statement = statement.outerjoin(
            WorkflowBucket,
            WorkflowBucket.workflow_key == Artifact.workflow_key,
        )
    if filters:
        statement = statement.where(*filters)
    try:
        items = session.exec(statement).all()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return ArtifactsPublic(data=[], count=0)
        raise

    return ArtifactsPublic(data=items, count=count)


@router.get("/{id}", response_model=ArtifactPublic)
def read_artifact(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
    """
    Get artifact by ID.
    """
    try:
        item = session.get(Artifact, id)
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Artifact not found")
        raise
    if not item:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return item


@router.post("/", response_model=ArtifactPublic)
def create_artifact(
    *, session: SessionDep, current_user: CurrentUser, item_in: ArtifactCreate
) -> Any:
    """
    Create a new artifact.

    Notes:
    - Deletes are not supported; supersede instead.
    """
    get_current_active_superuser(current_user)
    item = Artifact.model_validate(item_in)
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


@router.put("/{id}", response_model=ArtifactPublic)
def update_artifact(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    item_in: ArtifactUpdate,
) -> Any:
    """
    Update an artifact by superseding it.

    This endpoint never edits the existing row; it creates a new row and sets
    `superseded_by_id` on the previous artifact.
    """
    get_current_active_superuser(current_user)

    existing = session.get(Artifact, id)
    if not existing:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if existing.superseded_by_id is not None:
        raise HTTPException(status_code=409, detail="Cannot update a superseded artifact")

    update = item_in.model_dump(exclude_unset=True)
    new_item = Artifact(
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
def delete_artifact(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
    """
    Delete an artifact.

    Note: restricted to superusers. Deletion is blocked if the item is referenced.
    Prefer superseding instead of deleting.
    """

    get_current_active_superuser(current_user)
    item = session.get(Artifact, id)
    if not item:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # Block deletion if referenced by newer versions.
    newer_count = (
        session.exec(
            select(func.count()).select_from(Artifact).where(Artifact.superseded_by_id == id)
        ).one()
    )
    if newer_count and int(newer_count) > 0:
        raise HTTPException(status_code=409, detail="Artifact is referenced by newer versions")

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
                    "select count(*) from public.execution_artifact_link where artifact_id = :id"
                ),
                {"id": id},
            )
            .scalar_one()
        )
    except ProgrammingError as e:
        if not _is_missing_table_error(e):
            raise
    if linked_count and int(linked_count) > 0:
        raise HTTPException(status_code=409, detail="Artifact is linked from executions")

    session.delete(item)
    session.commit()
    return Message(message="Artifact deleted successfully")
