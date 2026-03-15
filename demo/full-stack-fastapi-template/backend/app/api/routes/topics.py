import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import ProgrammingError

from app.api.deps import CurrentUser, SessionDep
from app.core.topics import (
    build_topic_public,
    build_topic_rollup_public,
    list_topic_rows,
    match_topics,
    read_topic_row,
    refresh_topic_rollup,
)
from app.models import TopicMatchRequest, TopicMatchResult, TopicPublic, TopicRollupPublic, TopicsPublic

router = APIRouter(prefix="/topics", tags=["topics"])


def _is_missing_table_error(err: Exception) -> bool:
    message = str(err).lower()
    return "does not exist" in message and "relation" in message


@router.get("/", response_model=TopicsPublic)
def read_topics(
    session: SessionDep,
    current_user: CurrentUser,
    status: str | None = None,
    q: str | None = None,
) -> Any:
    """
    Retrieve Topics as compatibility views over Threads.
    """

    try:
        rows = list_topic_rows(session, status=status, q=q)
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return TopicsPublic(data=[], count=0)
        raise

    topics = [build_topic_public(row) for row in rows]
    return TopicsPublic(data=topics, count=len(topics))


@router.post("/match", response_model=TopicMatchResult)
def match_topics_route(
    session: SessionDep,
    current_user: CurrentUser,
    request: TopicMatchRequest,
) -> Any:
    """
    Match Topics using request signals and derive a confidence-based hydration policy.
    """

    try:
        return match_topics(session, request)
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return TopicMatchResult()
        raise


@router.get("/{topic_id}", response_model=TopicPublic)
def read_topic(session: SessionDep, current_user: CurrentUser, topic_id: uuid.UUID) -> Any:
    """
    Get a Topic compatibility view by ID.
    """

    try:
        row = read_topic_row(session, topic_id)
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Topic not found")
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return build_topic_public(row)


@router.get("/{topic_id}/rollup", response_model=TopicRollupPublic)
def read_topic_rollup(
    session: SessionDep,
    current_user: CurrentUser,
    topic_id: uuid.UUID,
) -> Any:
    """
    Read the Topic rollup, deriving it on the fly if needed.
    """

    try:
        row = read_topic_row(session, topic_id)
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Topic not found")
        raise

    if row is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    rollup = refresh_topic_rollup(session, topic_id, persist=False)
    if rollup is not None:
        return rollup
    return build_topic_rollup_public(row)


@router.post("/{topic_id}/rollup/refresh", response_model=TopicRollupPublic)
def refresh_topic_rollup_route(
    session: SessionDep,
    current_user: CurrentUser,
    topic_id: uuid.UUID,
) -> Any:
    """
    Refresh and persist the Topic rollup from current Cases.
    """

    try:
        rollup = refresh_topic_rollup(session, topic_id, persist=True)
        session.commit()
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            raise HTTPException(status_code=404, detail="Topic not found")
        raise

    if rollup is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return rollup
