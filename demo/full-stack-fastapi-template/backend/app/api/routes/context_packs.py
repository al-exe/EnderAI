from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import ProgrammingError

from app.api.deps import CurrentUser, SessionDep
from app.core.topics import build_context_pack
from app.models import ContextPackBuildRequest, ContextPackBuildResult

router = APIRouter(prefix="/context-packs", tags=["context-packs"])


def _is_missing_table_error(err: Exception) -> bool:
    message = str(err).lower()
    return "does not exist" in message and "relation" in message


@router.post("/build", response_model=ContextPackBuildResult)
def build_context_pack_route(
    session: SessionDep,
    current_user: CurrentUser,
    request: ContextPackBuildRequest,
) -> Any:
    """
    Build a compact ContextPack from matched Topics, prior Cases, and request signals.
    """

    try:
        return build_context_pack(session, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ProgrammingError as e:
        if _is_missing_table_error(e):
            return ContextPackBuildResult()
        raise
