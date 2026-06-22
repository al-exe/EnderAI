from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session

from app.api.deps import CurrentUser, SessionDep
from app.core.taskforce.evolution_review import (
    confirm_proposed_specialist,
    dismiss_document_contradiction_flag,
    list_review_items,
    reject_proposed_specialist,
)
from app.models import EvolutionReviewResponse

router = APIRouter(prefix="/v2/evolution", tags=["v2-evolution"])


@router.get("/review", response_model=EvolutionReviewResponse)
def evolution_review_queue(
    session: SessionDep,
    current_user: CurrentUser,
    demo: bool = Query(default=False),
) -> EvolutionReviewResponse:
    if current_user.organization_id is None and not demo:
        raise HTTPException(status_code=403, detail="Organization required")
    items = list_review_items(session, actor=current_user, demo=demo)
    return EvolutionReviewResponse.model_validate(items)


@router.post("/review/specialists/{specialist_id}/confirm")
def confirm_proposed_specialist_route(
    session: SessionDep,
    current_user: CurrentUser,
    specialist_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> dict[str, str]:
    try:
        specialist = confirm_proposed_specialist(
            session,
            actor=current_user,
            specialist_id=specialist_id,
            demo=demo,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return {"status": specialist.status, "slug": specialist.slug}


@router.post("/review/specialists/{specialist_id}/reject")
def reject_proposed_specialist_route(
    session: SessionDep,
    current_user: CurrentUser,
    specialist_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> dict[str, str]:
    try:
        specialist = reject_proposed_specialist(
            session,
            actor=current_user,
            specialist_id=specialist_id,
            demo=demo,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return {"status": specialist.status, "slug": specialist.slug}


@router.post("/review/documents/{document_id}/dismiss-contradiction")
def dismiss_document_contradiction_route(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> dict[str, str]:
    try:
        document = dismiss_document_contradiction_flag(
            session,
            actor=current_user,
            document_id=document_id,
            demo=demo,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return {"document_id": str(document.id), "evolution_stale": str(document.evolution_stale)}
