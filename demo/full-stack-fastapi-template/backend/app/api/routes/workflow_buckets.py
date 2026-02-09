from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.models import (
    Message,
    WorkflowBucket,
    WorkflowBucketCreate,
    WorkflowBucketPublic,
    WorkflowBucketUpdate,
    WorkflowBucketsPublic,
    get_datetime_utc,
)

router = APIRouter(prefix="/workflow-buckets", tags=["workflow_buckets"])


@router.get("/", response_model=WorkflowBucketsPublic)
def read_workflow_buckets(
    session: SessionDep,
    current_user: CurrentUser,
    q: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve workflow buckets (human-friendly labels for workflow_key).
    """

    q = q.strip() if q else None

    statement = select(WorkflowBucket)
    count_statement = select(func.count()).select_from(WorkflowBucket)
    if q:
        like = f"%{q}%"
        statement = statement.where(
            WorkflowBucket.workflow_key.ilike(like) | WorkflowBucket.bucket_name.ilike(like)
        )
        count_statement = count_statement.where(
            WorkflowBucket.workflow_key.ilike(like) | WorkflowBucket.bucket_name.ilike(like)
        )

    count = session.exec(count_statement).one()
    buckets = (
        session.exec(
            statement.order_by(WorkflowBucket.updated_at.desc()).offset(skip).limit(limit)
        ).all()
    )
    data = [
        WorkflowBucketPublic(
            workflow_key=b.workflow_key,
            bucket_name=b.bucket_name,
            created_at=b.created_at,
            updated_at=b.updated_at,
        )
        for b in buckets
    ]
    return WorkflowBucketsPublic(data=data, count=count)


@router.get("/{workflow_key}", response_model=WorkflowBucketPublic)
def read_workflow_bucket(session: SessionDep, current_user: CurrentUser, workflow_key: str) -> Any:
    bucket = session.get(WorkflowBucket, workflow_key)
    if not bucket:
        raise HTTPException(status_code=404, detail="Workflow bucket not found")
    return WorkflowBucketPublic(
        workflow_key=bucket.workflow_key,
        bucket_name=bucket.bucket_name,
        created_at=bucket.created_at,
        updated_at=bucket.updated_at,
    )


@router.post("/", response_model=WorkflowBucketPublic, status_code=201)
def create_workflow_bucket(
    session: SessionDep,
    current_user: CurrentUser,
    bucket_in: WorkflowBucketCreate,
) -> Any:
    get_current_active_superuser(current_user)
    workflow_key = bucket_in.workflow_key.strip()
    bucket_name = bucket_in.bucket_name.strip()
    if not workflow_key:
        raise HTTPException(status_code=422, detail="workflow_key must not be empty")
    if not bucket_name:
        raise HTTPException(status_code=422, detail="bucket_name must not be empty")

    existing = session.get(WorkflowBucket, workflow_key)
    if existing:
        raise HTTPException(status_code=409, detail="Workflow bucket already exists")

    now = get_datetime_utc()
    bucket = WorkflowBucket(
        workflow_key=workflow_key,
        bucket_name=bucket_name,
        created_at=now,
        updated_at=now,
    )
    session.add(bucket)
    session.commit()
    session.refresh(bucket)
    return WorkflowBucketPublic(
        workflow_key=bucket.workflow_key,
        bucket_name=bucket.bucket_name,
        created_at=bucket.created_at,
        updated_at=bucket.updated_at,
    )


@router.put("/{workflow_key}", response_model=WorkflowBucketPublic)
def update_workflow_bucket(
    session: SessionDep,
    current_user: CurrentUser,
    workflow_key: str,
    bucket_in: WorkflowBucketUpdate,
) -> Any:
    get_current_active_superuser(current_user)
    bucket = session.get(WorkflowBucket, workflow_key)
    if not bucket:
        raise HTTPException(status_code=404, detail="Workflow bucket not found")

    bucket_name = bucket_in.bucket_name.strip()
    if not bucket_name:
        raise HTTPException(status_code=422, detail="bucket_name must not be empty")

    bucket.bucket_name = bucket_name
    bucket.updated_at = get_datetime_utc()
    session.add(bucket)
    session.commit()
    session.refresh(bucket)
    return WorkflowBucketPublic(
        workflow_key=bucket.workflow_key,
        bucket_name=bucket.bucket_name,
        created_at=bucket.created_at,
        updated_at=bucket.updated_at,
    )


@router.delete("/{workflow_key}", response_model=Message)
def delete_workflow_bucket(
    session: SessionDep,
    current_user: CurrentUser,
    workflow_key: str,
) -> Any:
    get_current_active_superuser(current_user)
    bucket = session.get(WorkflowBucket, workflow_key)
    if not bucket:
        raise HTTPException(status_code=404, detail="Workflow bucket not found")
    session.delete(bucket)
    session.commit()
    return Message(message="Workflow bucket deleted successfully")

