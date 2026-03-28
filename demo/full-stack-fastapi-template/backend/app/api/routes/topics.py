import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.demo import ensure_demo_workspace
from app.core.topics import (
    allocate_topic_identity,
    build_topic_public_current,
    claim_legacy_orphan_topics_for_owner,
    count_topics,
    list_topic_models,
    match_topics,
    read_topic_model,
    refresh_topic_rollup,
)
from app.models import (
    Topic,
    TopicCreate,
    TopicMatchRequest,
    TopicMatchResult,
    TopicPublic,
    TopicRollupPublic,
    TopicsPublic,
    TopicUpdate,
    get_datetime_utc,
)

router = APIRouter(prefix="/topics", tags=["topics"])


def _owner_scope_id(current_user: CurrentUser) -> uuid.UUID:
    return current_user.id


@router.get("/", response_model=TopicsPublic)
def read_topics(
    session: SessionDep,
    current_user: CurrentUser,
    demo: bool = Query(default=False),
    status: str | None = None,
    q: str | None = None,
    workflow_key: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    owner_id = _owner_scope_id(current_user)
    if demo and ensure_demo_workspace(session, current_user):
        session.commit()
        session.refresh(current_user)
    claimed = claim_legacy_orphan_topics_for_owner(session, owner_id)
    if claimed:
        session.commit()
    topics = list_topic_models(
        session,
        owner_id=owner_id,
        demo=demo,
        status=status,
        q=q,
        workflow_key=workflow_key,
        skip=skip,
        limit=limit,
    )
    return TopicsPublic(
        data=[
            build_topic_public_current(session, topic, owner_id=owner_id, demo=demo)
            for topic in topics
        ],
        count=count_topics(
            session,
            owner_id=owner_id,
            demo=demo,
            status=status,
            q=q,
            workflow_key=workflow_key,
        ),
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

    owner_id = _owner_scope_id(current_user)
    slug, workflow_key = allocate_topic_identity(session, title, topic_in.workflow_key)
    now = get_datetime_utc()
    topic = Topic(
        title=title,
        slug=slug,
        workflow_key=workflow_key,
        description=topic_in.description.strip() if isinstance(topic_in.description, str) and topic_in.description.strip() else None,
        aliases=[alias.strip() for alias in topic_in.aliases if isinstance(alias, str) and alias.strip()],
        status=topic_in.status.strip() if topic_in.status.strip() else "open",
        owner_ids=[str(owner_id)],
        created_at=now,
        updated_at=now,
        last_used_at=now,
    )
    session.add(topic)
    session.commit()
    session.refresh(topic)
    refresh_topic_rollup(session, topic.id, persist=True, owner_id=owner_id)
    session.commit()
    session.refresh(topic)
    return build_topic_public_current(session, topic, owner_id=owner_id)


@router.post("/match", response_model=TopicMatchResult)
def match_topics_route(
    session: SessionDep,
    current_user: CurrentUser,
    request: TopicMatchRequest,
    demo: bool = Query(default=False),
) -> Any:
    owner_id = _owner_scope_id(current_user)
    if demo and ensure_demo_workspace(session, current_user):
        session.commit()
        session.refresh(current_user)
    claimed = claim_legacy_orphan_topics_for_owner(session, owner_id)
    if claimed:
        session.commit()
    return match_topics(session, request, owner_id=owner_id, demo=demo)


@router.get("/{topic_id}", response_model=TopicPublic)
def read_topic(
    session: SessionDep,
    current_user: CurrentUser,
    topic_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> Any:
    owner_id = _owner_scope_id(current_user)
    if demo and ensure_demo_workspace(session, current_user):
        session.commit()
        session.refresh(current_user)
    claimed = claim_legacy_orphan_topics_for_owner(session, owner_id, topic_id=topic_id)
    if claimed:
        session.commit()
    topic = read_topic_model(session, topic_id, owner_id=owner_id, demo=demo)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return build_topic_public_current(session, topic, owner_id=owner_id, demo=demo)


@router.patch("/{topic_id}", response_model=TopicPublic)
def update_topic(
    session: SessionDep,
    current_user: CurrentUser,
    topic_id: uuid.UUID,
    topic_in: TopicUpdate,
    demo: bool = Query(default=False),
) -> Any:
    owner_id = _owner_scope_id(current_user)
    if demo and ensure_demo_workspace(session, current_user):
        session.commit()
        session.refresh(current_user)
    claimed = claim_legacy_orphan_topics_for_owner(session, owner_id, topic_id=topic_id)
    if claimed:
        session.commit()
    topic = read_topic_model(session, topic_id, owner_id=owner_id, demo=demo)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    update = topic_in.model_dump(exclude_unset=True)
    if not update:
        raise HTTPException(status_code=422, detail="No fields to update")
    if "owner_ids" in update:
        raise HTTPException(
            status_code=403,
            detail="owner_ids cannot be changed through this endpoint",
        )

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

    topic.updated_at = get_datetime_utc()
    session.add(topic)
    session.commit()
    session.refresh(topic)
    refresh_topic_rollup(session, topic.id, persist=True, owner_id=owner_id, demo=demo)
    session.commit()
    session.refresh(topic)
    return build_topic_public_current(session, topic, owner_id=owner_id, demo=demo)


@router.get("/{topic_id}/rollup", response_model=TopicRollupPublic)
def read_topic_rollup(
    session: SessionDep,
    current_user: CurrentUser,
    topic_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> Any:
    owner_id = _owner_scope_id(current_user)
    if demo and ensure_demo_workspace(session, current_user):
        session.commit()
        session.refresh(current_user)
    claimed = claim_legacy_orphan_topics_for_owner(session, owner_id, topic_id=topic_id)
    if claimed:
        session.commit()
    topic = read_topic_model(session, topic_id, owner_id=owner_id, demo=demo)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    rollup = refresh_topic_rollup(
        session,
        topic_id,
        persist=False,
        owner_id=owner_id,
        demo=demo,
    )
    if rollup is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return rollup


@router.post("/{topic_id}/rollup/refresh", response_model=TopicRollupPublic)
def refresh_topic_rollup_route(
    session: SessionDep,
    current_user: CurrentUser,
    topic_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> Any:
    owner_id = _owner_scope_id(current_user)
    if demo and ensure_demo_workspace(session, current_user):
        session.commit()
        session.refresh(current_user)
    claimed = claim_legacy_orphan_topics_for_owner(session, owner_id, topic_id=topic_id)
    if claimed:
        session.commit()
    topic = read_topic_model(session, topic_id, owner_id=owner_id, demo=demo)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    rollup = refresh_topic_rollup(
        session,
        topic_id,
        persist=True,
        owner_id=owner_id,
        demo=demo,
    )
    if rollup is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return rollup
