import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActiveUser, CurrentUser, SessionDep
from app.core.v2_documents import (
    apply_v2_document_update,
    build_v2_document_public,
    ensure_v2_documents_demo_seed,
    get_v2_document_for_actor,
    list_v2_documents_for_actor,
)
from app.models import (
    V2Document,
    V2DocumentCreate,
    V2DocumentPublic,
    V2DocumentsPublic,
    V2DocumentUpdate,
    get_datetime_utc,
)

router = APIRouter(prefix="/v2/documents", tags=["v2-documents"])


def _maybe_seed_demo(
    session: SessionDep, current_user: CurrentUser, demo: bool
) -> None:
    if (
        demo
        and current_user.is_active
        and ensure_v2_documents_demo_seed(session, current_user)
    ):
        session.commit()


@router.get("/", response_model=V2DocumentsPublic)
def read_v2_documents(
    session: SessionDep,
    current_user: CurrentUser,
    demo: bool = Query(default=False),
) -> Any:
    _maybe_seed_demo(session, current_user, demo)
    documents = list_v2_documents_for_actor(session, current_user, demo=demo)
    return V2DocumentsPublic(
        data=[build_v2_document_public(document) for document in documents],
        count=len(documents),
    )


@router.post("/", response_model=V2DocumentPublic, status_code=201)
def create_v2_document(
    session: SessionDep,
    current_user: ActiveUser,
    document_in: V2DocumentCreate,
    demo: bool = Query(default=False),
) -> Any:
    _maybe_seed_demo(session, current_user, demo)
    payload = document_in.model_dump(mode="json")
    visibility = payload.get("visibility", "private")
    if visibility == "organization" and current_user.organization_id is None:
        raise HTTPException(
            status_code=422,
            detail="User must belong to an organization to share a document",
        )
    now = get_datetime_utc()
    document = V2Document(
        owner_id=current_user.id,
        organization_id=(
            current_user.organization_id if visibility == "organization" else None
        ),
        visibility=visibility,
        title=payload["title"].strip(),
        description=payload.get("description", ""),
        human_summary=payload.get("human_summary", ""),
        ai_generated_summary=payload.get("ai_generated_summary", ""),
        collaborators=list(payload.get("collaborators") or []),
        main_body=list(payload.get("main_body") or []),
        details_file_name=payload.get("details_file_name", ""),
        details_markdown_sections=list(payload.get("details_markdown_sections") or []),
        is_demo=demo,
        created_at=now,
        updated_at=now,
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return build_v2_document_public(document)


@router.get("/{document_id}", response_model=V2DocumentPublic)
def read_v2_document(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> Any:
    _maybe_seed_demo(session, current_user, demo)
    document = get_v2_document_for_actor(
        session, current_user, document_id, demo=demo
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return build_v2_document_public(document)


@router.patch("/{document_id}", response_model=V2DocumentPublic)
def update_v2_document(
    session: SessionDep,
    current_user: ActiveUser,
    document_id: uuid.UUID,
    document_in: V2DocumentUpdate,
    demo: bool = Query(default=False),
) -> Any:
    _maybe_seed_demo(session, current_user, demo)
    document = get_v2_document_for_actor(
        session, current_user, document_id, demo=demo
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if "visibility" in document_in.model_fields_set:
        if document.owner_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Only the document owner can change visibility",
            )
        if document_in.visibility == "organization":
            if current_user.organization_id is None:
                raise HTTPException(
                    status_code=422,
                    detail="User must belong to an organization to share a document",
                )
            document.organization_id = current_user.organization_id
        else:
            document.organization_id = None
    if not apply_v2_document_update(document, document_in):
        raise HTTPException(status_code=422, detail="No fields to update")
    session.add(document)
    session.commit()
    session.refresh(document)
    return build_v2_document_public(document)
