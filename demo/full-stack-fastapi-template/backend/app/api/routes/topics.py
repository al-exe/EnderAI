import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.topics import (
    allocate_topic_identity,
    build_topic_public_current,
    build_topic_rollup_public,
    count_topics,
    list_topic_models,
    match_topics,
    read_topic_model,
    refresh_topic_rollup,
)
from app.models import Topic, TopicCreate, TopicMatchRequest, TopicMatchResult, TopicPublic, TopicRollupPublic, TopicsPublic, TopicUpdate, get_datetime_utc

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("/", response_model=TopicsPublic)
def read_topics(
    session: SessionDep,
    current_user: CurrentUser,
    status: str | None = None,
    q: str | None = None,
    workflow_key: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    topics = list_topic_models(
        session,
        status=status,
        q=q,
        workflow_key=workflow_key,
        skip=skip,
        limit=limit,
    )
    return TopicsPublic(
        data=[build_topic_public_current(session, topic) for topic in topics],
        count=count_topics(session, status=status, q=q, workflow_key=workflow_key),
    )


@router.post("/", response_model=TopicPublic, status_code=201)
def create_topic(
    session: SessionDep,
    current_user: CurrentUser,
    topic_in: TopicCreate,
) -> Any:
    title = topic_in.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title must not be empty")

    slug, workflow_key = allocate_topic_identity(session, title, topic_in.workflow_key)
    now = get_datetime_utc()
    topic = Topic(
        title=title,
        slug=slug,
        workflow_key=workflow_key,
        description=topic_in.description.strip() if isinstance(topic_in.description, str) and topic_in.description.strip() else None,
        aliases=[alias.strip() for alias in topic_in.aliases if isinstance(alias, str) and alias.strip()],
        status=topic_in.status.strip() if topic_in.status.strip() else "open",
        owner_ids=[str(owner_id) for owner_id in topic_in.owner_ids],
        created_at=now,
        updated_at=now,
        last_used_at=now,
    )
    session.add(topic)
    session.commit()
    session.refresh(topic)
    refresh_topic_rollup(session, topic.id, persist=True)
    session.commit()
    session.refresh(topic)
    return build_topic_public_current(session, topic)


@router.post("/match", response_model=TopicMatchResult)
def match_topics_route(
    session: SessionDep,
    current_user: CurrentUser,
    request: TopicMatchRequest,
) -> Any:
    return match_topics(session, request)


@router.get("/{topic_id}", response_model=TopicPublic)
def read_topic(session: SessionDep, current_user: CurrentUser, topic_id: uuid.UUID) -> Any:
    topic = read_topic_model(session, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return build_topic_public_current(session, topic)


@router.patch("/{topic_id}", response_model=TopicPublic)
def update_topic(
    session: SessionDep,
    current_user: CurrentUser,
    topic_id: uuid.UUID,
    topic_in: TopicUpdate,
) -> Any:
    topic = read_topic_model(session, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    update = topic_in.model_dump(exclude_unset=True)
    if not update:
        raise HTTPException(status_code=422, detail="No fields to update")

    if "title" in update and update["title"] is not None:
        title = str(update["title"]).strip()
        if not title:
            raise HTTPException(status_code=422, detail="title must not be empty")
        topic.title = title
        if "workflow_key" not in update:
            topic.slug = title.lower().strip().replace(" ", "-")
    if "workflow_key" in update and update["workflow_key"] is not None:
        workflow_key = str(update["workflow_key"]).strip()
        if not workflow_key:
            raise HTTPException(status_code=422, detail="workflow_key must not be empty")
        duplicate = session.exec(select(Topic.id).where(Topic.workflow_key == workflow_key, Topic.id != topic.id)).first()
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="workflow_key already exists")
        topic.workflow_key = workflow_key
    if "description" in update:
        topic.description = update["description"].strip() if isinstance(update["description"], str) and update["description"].strip() else None
    if "aliases" in update and update["aliases"] is not None:
        topic.aliases = [alias.strip() for alias in update["aliases"] if isinstance(alias, str) and alias.strip()]
    if "status" in update and update["status"] is not None:
        status = str(update["status"]).strip()
        if not status:
            raise HTTPException(status_code=422, detail="status must not be empty")
        topic.status = status
    if "owner_ids" in update and update["owner_ids"] is not None:
        topic.owner_ids = [str(owner_id) for owner_id in update["owner_ids"]]

    topic.updated_at = get_datetime_utc()
    session.add(topic)
    session.commit()
    session.refresh(topic)
    refresh_topic_rollup(session, topic.id, persist=True)
    session.commit()
    session.refresh(topic)
    return build_topic_public_current(session, topic)


@router.get("/{topic_id}/rollup", response_model=TopicRollupPublic)
def read_topic_rollup(
    session: SessionDep,
    current_user: CurrentUser,
    topic_id: uuid.UUID,
) -> Any:
    topic = read_topic_model(session, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    rollup = refresh_topic_rollup(session, topic_id, persist=False)
    if rollup is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return rollup


@router.post("/{topic_id}/rollup/refresh", response_model=TopicRollupPublic)
def refresh_topic_rollup_route(
    session: SessionDep,
    current_user: CurrentUser,
    topic_id: uuid.UUID,
) -> Any:
    topic = read_topic_model(session, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    rollup = refresh_topic_rollup(session, topic_id, persist=True)
    if rollup is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    session.commit()
    session.refresh(topic)
    return build_topic_rollup_public(topic)
