from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SessionDep
from app.core.topics import build_context_pack
from app.models import ContextPackBuildRequest, ContextPackBuildResult

router = APIRouter(prefix="/context-packs", tags=["context-packs"])


def _owner_scope_id(current_user: CurrentUser):
    return current_user.id


@router.post("/build", response_model=ContextPackBuildResult)
def build_context_pack_route(
    session: SessionDep,
    current_user: CurrentUser,
    request: ContextPackBuildRequest,
) -> Any:
    try:
        return build_context_pack(
            session,
            request,
            owner_id=_owner_scope_id(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
