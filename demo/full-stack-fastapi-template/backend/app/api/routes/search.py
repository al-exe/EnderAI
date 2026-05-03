from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, SessionDep
from app.core.demo import ensure_demo_workspace
from app.core.search import search_topics_and_cases
from app.models import SearchResultsPublic

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/", response_model=SearchResultsPublic)
def search_route(
    session: SessionDep,
    current_user: CurrentUser,
    q: str,
    demo: bool = Query(default=False),
    limit_per_kind: int = Query(default=5, ge=1, le=10),
) -> Any:
    if current_user.is_active and demo and ensure_demo_workspace(session, current_user):
        session.commit()
        session.refresh(current_user)
    if len(q.strip()) < 2:
        raise HTTPException(
            status_code=422,
            detail="q must be at least 2 non-space characters",
        )

    return search_topics_and_cases(
        session,
        q,
        owner_id=current_user.id,
        demo=demo,
        limit_per_kind=limit_per_kind,
    )
