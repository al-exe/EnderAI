from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, SessionDep
from app.core.demo import ensure_demo_workspace
from app.core.topics import build_context_pack, claim_legacy_orphan_topics_for_owner
from app.models import ContextPackBuildRequest, ContextPackBuildResult

router = APIRouter(prefix="/context-packs", tags=["context-packs"])


def _owner_scope_id(current_user: CurrentUser):
    return current_user.id


@router.post("/build", response_model=ContextPackBuildResult)
def build_context_pack_route(
    session: SessionDep,
    current_user: CurrentUser,
    request: ContextPackBuildRequest,
    demo: bool = Query(default=False),
) -> Any:
    owner_id = _owner_scope_id(current_user)
    if current_user.is_active and demo and ensure_demo_workspace(session, current_user):
        session.commit()
        session.refresh(current_user)
    claimed = (
        claim_legacy_orphan_topics_for_owner(session, owner_id)
        if current_user.is_active
        else False
    )
    if claimed:
        session.commit()
    try:
        return build_context_pack(
            session,
            request,
            owner_id=owner_id,
            demo=demo,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
