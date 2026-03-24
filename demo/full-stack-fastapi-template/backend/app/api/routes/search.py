from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, SessionDep
from app.core.search import search_topics_and_cases
from app.models import SearchResultsPublic

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/", response_model=SearchResultsPublic)
def search_route(
    session: SessionDep,
    _current_user: CurrentUser,
    q: str,
    limit_per_kind: int = Query(default=5, ge=1, le=10),
) -> Any:
    if len(q.strip()) < 2:
        raise HTTPException(
            status_code=422,
            detail="q must be at least 2 non-space characters",
        )

    return search_topics_and_cases(session, q, limit_per_kind=limit_per_kind)
