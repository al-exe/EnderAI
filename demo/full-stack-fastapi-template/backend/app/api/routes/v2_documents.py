import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.metrics import (
    record_document_created,
    record_document_reused,
    record_document_updated,
    record_usage,
)
from app.core.taskforce.evolution_doc_patch import (
    list_evolution_changelogs,
    revert_evolution_changelog,
)
from app.core.v2_documents import (
    apply_v2_document_update,
    build_v2_document_folder_public,
    build_v2_document_public,
    can_update_v2_document,
    ensure_v2_documents_demo_seed,
    get_v2_document_folder_for_actor,
    get_v2_document_for_actor,
    list_v2_document_folders_for_actor,
    list_v2_document_shares_public,
    list_v2_documents_for_actor,
    refresh_v2_document_token_counts,
)
from app.models import (
    MetricsEventPublic,
    MetricsUsageRecorded,
    TaskforceReusePayload,
    TaskforceUsagePayload,
    User,
    V2Document,
    V2DocumentCreate,
    V2DocumentEvolutionChangelogPublic,
    V2DocumentFavorite,
    V2DocumentFolder,
    V2DocumentFolderCreate,
    V2DocumentFolderPublic,
    V2DocumentFoldersPublic,
    V2DocumentFolderUpdate,
    V2DocumentPublic,
    V2DocumentShare,
    V2DocumentSharesPublic,
    V2DocumentSharesUpdate,
    V2DocumentsPublic,
    V2DocumentUpdate,
    get_datetime_utc,
)

router = APIRouter(prefix="/v2/documents", tags=["v2-documents"])


def _maybe_seed_demo(
    session: SessionDep, current_user: CurrentUser, demo: bool
) -> None:
    if demo and ensure_v2_documents_demo_seed(session, current_user):
        session.commit()


def _validate_folder_access(
    session: SessionDep,
    current_user: CurrentUser,
    folder_id: uuid.UUID | None,
    *,
    demo: bool,
) -> V2DocumentFolder | None:
    if folder_id is None:
        return None
    folder = get_v2_document_folder_for_actor(
        session, current_user, folder_id, demo=demo
    )
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


def _validate_parent_folder(
    session: SessionDep,
    current_user: CurrentUser,
    parent_folder_id: uuid.UUID | None,
    *,
    folder_id: uuid.UUID | None = None,
    demo: bool = False,
) -> V2DocumentFolder | None:
    if parent_folder_id is None:
        return None
    if folder_id is not None and parent_folder_id == folder_id:
        raise HTTPException(status_code=422, detail="Folder cannot contain itself")

    parent = get_v2_document_folder_for_actor(
        session, current_user, parent_folder_id, demo=demo
    )
    if parent is None:
        raise HTTPException(status_code=422, detail="Parent folder not found")

    seen_folder_ids: set[uuid.UUID] = set()
    current_parent = parent
    while current_parent.parent_folder_id is not None:
        ancestor_id = current_parent.parent_folder_id
        if ancestor_id in seen_folder_ids:
            raise HTTPException(status_code=422, detail="Folder hierarchy has a cycle")
        if folder_id is not None and ancestor_id == folder_id:
            raise HTTPException(
                status_code=422,
                detail="Folder cannot be moved under one of its descendants",
            )
        seen_folder_ids.add(ancestor_id)
        ancestor = get_v2_document_folder_for_actor(
            session, current_user, ancestor_id, demo=demo
        )
        if ancestor is None:
            break
        current_parent = ancestor

    return parent


def _require_document_owner(document: V2Document, current_user: CurrentUser) -> None:
    if document.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the document owner can manage this document setting",
        )


@router.get("/", response_model=V2DocumentsPublic)
def read_v2_documents(
    session: SessionDep,
    current_user: CurrentUser,
    demo: bool = Query(default=False),
) -> Any:
    _maybe_seed_demo(session, current_user, demo)
    documents = list_v2_documents_for_actor(session, current_user, demo=demo)
    return V2DocumentsPublic(
        data=[
            build_v2_document_public(
                document, session=session, actor=current_user, demo=demo
            )
            for document in documents
        ],
        count=len(documents),
    )


@router.get("/folders/", response_model=V2DocumentFoldersPublic)
def read_v2_document_folders(
    session: SessionDep,
    current_user: CurrentUser,
    demo: bool = Query(default=False),
) -> Any:
    folders = list_v2_document_folders_for_actor(session, current_user, demo=demo)
    return V2DocumentFoldersPublic(
        data=[build_v2_document_folder_public(folder) for folder in folders],
        count=len(folders),
    )


@router.post("/folders/", response_model=V2DocumentFolderPublic, status_code=201)
def create_v2_document_folder(
    session: SessionDep,
    current_user: CurrentUser,
    folder_in: V2DocumentFolderCreate,
    demo: bool = Query(default=False),
) -> Any:
    visibility = folder_in.visibility
    if visibility == "organization" and current_user.organization_id is None:
        raise HTTPException(
            status_code=422,
            detail="User must belong to an organization to share a folder",
        )
    if demo and visibility == "organization":
        # Demo-mode folders are always private to the demo account; the
        # organization scope would leak demo content to real org members.
        raise HTTPException(
            status_code=422,
            detail="Demo-mode folders cannot be shared with an organization",
        )
    parent_folder = _validate_parent_folder(
        session, current_user, folder_in.parent_folder_id, demo=demo
    )
    now = get_datetime_utc()
    folder = V2DocumentFolder(
        owner_id=current_user.id,
        organization_id=(
            current_user.organization_id if visibility == "organization" else None
        ),
        parent_folder_id=parent_folder.id if parent_folder else None,
        name=folder_in.name.strip(),
        visibility=visibility,
        is_demo=demo,
        created_at=now,
        updated_at=now,
    )
    session.add(folder)
    session.commit()
    session.refresh(folder)
    return build_v2_document_folder_public(folder)


@router.patch("/folders/{folder_id}", response_model=V2DocumentFolderPublic)
def update_v2_document_folder(
    session: SessionDep,
    current_user: CurrentUser,
    folder_id: uuid.UUID,
    folder_in: V2DocumentFolderUpdate,
    demo: bool = Query(default=False),
) -> Any:
    folder = get_v2_document_folder_for_actor(
        session, current_user, folder_id, demo=demo
    )
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    if folder.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the folder owner can update this folder",
        )
    payload = folder_in.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=422, detail="No fields to update")
    if "name" in payload:
        folder.name = payload["name"].strip()
    if "visibility" in payload:
        visibility = payload["visibility"]
        if visibility == "organization" and current_user.organization_id is None:
            raise HTTPException(
                status_code=422,
                detail="User must belong to an organization to share a folder",
            )
        if demo and visibility == "organization":
            raise HTTPException(
                status_code=422,
                detail="Demo-mode folders cannot be shared with an organization",
            )
        folder.visibility = visibility
        folder.organization_id = (
            current_user.organization_id if visibility == "organization" else None
        )
    if "parent_folder_id" in payload:
        parent_folder = _validate_parent_folder(
            session,
            current_user,
            folder_in.parent_folder_id,
            folder_id=folder.id,
            demo=demo,
        )
        folder.parent_folder_id = parent_folder.id if parent_folder else None
    folder.updated_at = get_datetime_utc()
    session.add(folder)
    session.commit()
    session.refresh(folder)
    return build_v2_document_folder_public(folder)


@router.delete("/folders/{folder_id}", status_code=204)
def delete_v2_document_folder(
    session: SessionDep,
    current_user: CurrentUser,
    folder_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> None:
    folder = get_v2_document_folder_for_actor(
        session, current_user, folder_id, demo=demo
    )
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    if folder.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the folder owner can delete this folder",
        )
    documents = session.exec(
        select(V2Document).where(V2Document.folder_id == folder.id)
    ).all()
    for document in documents:
        document.folder_id = None
        document.updated_at = get_datetime_utc()
        session.add(document)
    child_folders = session.exec(
        select(V2DocumentFolder).where(V2DocumentFolder.parent_folder_id == folder.id)
    ).all()
    for child_folder in child_folders:
        child_folder.parent_folder_id = None
        child_folder.updated_at = get_datetime_utc()
        session.add(child_folder)
    session.delete(folder)
    session.commit()


@router.post("/", response_model=V2DocumentPublic, status_code=201)
def create_v2_document(
    session: SessionDep,
    current_user: CurrentUser,
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
    folder = _validate_folder_access(
        session, current_user, document_in.folder_id, demo=demo
    )
    now = get_datetime_utc()
    document = V2Document(
        owner_id=current_user.id,
        organization_id=(
            current_user.organization_id if visibility == "organization" else None
        ),
        folder_id=folder.id if folder else None,
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
    refresh_v2_document_token_counts(document)
    session.add(document)
    session.flush()
    record_document_created(
        session,
        user=current_user,
        document=document,
        usage=document_in.usage,
        is_demo=demo,
    )
    session.commit()
    session.refresh(document)
    return build_v2_document_public(
        document, session=session, actor=current_user, demo=demo
    )


@router.get("/{document_id}", response_model=V2DocumentPublic)
def read_v2_document(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> Any:
    _maybe_seed_demo(session, current_user, demo)
    document = get_v2_document_for_actor(session, current_user, document_id, demo=demo)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return build_v2_document_public(
        document, session=session, actor=current_user, demo=demo
    )


@router.get("/{document_id}/shares/", response_model=V2DocumentSharesPublic)
def read_v2_document_shares(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
) -> Any:
    document = get_v2_document_for_actor(session, current_user, document_id, demo=False)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the document owner can view member shares",
        )
    shares = list_v2_document_shares_public(session, document.id)
    return V2DocumentSharesPublic(data=shares, count=len(shares))


@router.put("/{document_id}/shares/", response_model=V2DocumentSharesPublic)
def replace_v2_document_shares(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
    shares_in: V2DocumentSharesUpdate,
) -> Any:
    document = get_v2_document_for_actor(session, current_user, document_id, demo=False)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    _require_document_owner(document, current_user)
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=422,
            detail="User must belong to an organization to share a document",
        )

    next_permissions: dict[uuid.UUID, str] = {}
    for assignment in shares_in.shares:
        target = session.get(User, assignment.user_id)
        if (
            target is None
            or target.id == current_user.id
            or target.organization_id != current_user.organization_id
        ):
            raise HTTPException(
                status_code=422,
                detail="Documents can only be shared with organization members",
            )
        next_permissions[target.id] = assignment.permission

    existing = session.exec(
        select(V2DocumentShare).where(V2DocumentShare.document_id == document.id)
    ).all()
    existing_by_user = {share.user_id: share for share in existing}
    now = get_datetime_utc()

    for share in existing:
        if share.user_id not in next_permissions:
            session.delete(share)

    for user_id, permission in next_permissions.items():
        share = existing_by_user.get(user_id)
        if share:
            share.permission = permission
            share.updated_at = now
        else:
            share = V2DocumentShare(
                document_id=document.id,
                user_id=user_id,
                permission=permission,
                created_by_user_id=current_user.id,
                created_at=now,
                updated_at=now,
            )
        session.add(share)

    document.updated_at = now
    session.add(document)
    session.commit()
    shares = list_v2_document_shares_public(session, document.id)
    return V2DocumentSharesPublic(data=shares, count=len(shares))


@router.put("/{document_id}/favorite", response_model=V2DocumentPublic)
def favorite_v2_document(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> Any:
    _maybe_seed_demo(session, current_user, demo)
    document = get_v2_document_for_actor(session, current_user, document_id, demo=demo)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    favorite = session.exec(
        select(V2DocumentFavorite)
        .where(V2DocumentFavorite.document_id == document.id)
        .where(V2DocumentFavorite.user_id == current_user.id)
    ).first()
    if favorite is None:
        favorite = V2DocumentFavorite(
            document_id=document.id,
            user_id=current_user.id,
            created_at=get_datetime_utc(),
        )
        session.add(favorite)
        session.commit()

    return build_v2_document_public(
        document, session=session, actor=current_user, demo=demo
    )


@router.delete("/{document_id}/favorite", response_model=V2DocumentPublic)
def unfavorite_v2_document(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> Any:
    _maybe_seed_demo(session, current_user, demo)
    document = get_v2_document_for_actor(session, current_user, document_id, demo=demo)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    favorite = session.exec(
        select(V2DocumentFavorite)
        .where(V2DocumentFavorite.document_id == document.id)
        .where(V2DocumentFavorite.user_id == current_user.id)
    ).first()
    if favorite is not None:
        session.delete(favorite)
        session.commit()

    return build_v2_document_public(
        document, session=session, actor=current_user, demo=demo
    )


@router.patch("/{document_id}", response_model=V2DocumentPublic)
def update_v2_document(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
    document_in: V2DocumentUpdate,
    demo: bool = Query(default=False),
) -> Any:
    _maybe_seed_demo(session, current_user, demo)
    document = get_v2_document_for_actor(session, current_user, document_id, demo=demo)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not can_update_v2_document(session, document, current_user, demo=demo):
        raise HTTPException(
            status_code=403,
            detail="You do not have edit access to this document",
        )
    if "visibility" in document_in.model_fields_set:
        _require_document_owner(document, current_user)
        if document_in.visibility == "organization":
            if current_user.organization_id is None:
                raise HTTPException(
                    status_code=422,
                    detail="User must belong to an organization to share a document",
                )
            document.organization_id = current_user.organization_id
        else:
            document.organization_id = None
    if "folder_id" in document_in.model_fields_set:
        _require_document_owner(document, current_user)
        _validate_folder_access(session, current_user, document_in.folder_id, demo=demo)
    if (
        "created_at" in document_in.model_fields_set
        or "updated_at" in document_in.model_fields_set
    ):
        _require_document_owner(document, current_user)
    if not apply_v2_document_update(document, document_in):
        if document_in.usage is not None:
            # Allow callers to PATCH purely to record usage. We still need the
            # primary document.updated event so the read path sees activity.
            record_document_updated(
                session,
                user=current_user,
                document=document,
                usage=document_in.usage,
                is_demo=demo,
            )
            session.commit()
            session.refresh(document)
            return build_v2_document_public(
                document, session=session, actor=current_user, demo=demo
            )
        raise HTTPException(status_code=422, detail="No fields to update")
    session.add(document)
    session.flush()
    record_document_updated(
        session,
        user=current_user,
        document=document,
        usage=document_in.usage,
        is_demo=demo,
    )
    session.commit()
    session.refresh(document)
    return build_v2_document_public(
        document, session=session, actor=current_user, demo=demo
    )


@router.get(
    "/{document_id}/evolution-changelog",
    response_model=list[V2DocumentEvolutionChangelogPublic],
)
def read_v2_document_evolution_changelog(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> Any:
    document = get_v2_document_for_actor(session, current_user, document_id, demo=demo)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    rows = list_evolution_changelogs(session, document_id=document.id)
    return [
        V2DocumentEvolutionChangelogPublic(
            id=row.id,
            document_id=row.document_id,
            source_session_id=row.source_session_id,
            confidence=row.confidence,
            summary_snapshot=dict(row.summary_snapshot or {}),
            diff_or_section=dict(row.diff_or_section or {}),
            created_at=row.created_at,
            reverted_at=row.reverted_at,
        )
        for row in rows
    ]


@router.post(
    "/{document_id}/evolution-changelog/{changelog_id}/revert",
    response_model=V2DocumentPublic,
)
def revert_v2_document_evolution_changelog(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
    changelog_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> Any:
    document = get_v2_document_for_actor(session, current_user, document_id, demo=demo)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not can_update_v2_document(session, document, current_user, demo=demo):
        raise HTTPException(
            status_code=403,
            detail="You do not have edit access to this document",
        )
    try:
        restored = revert_evolution_changelog(
            session,
            actor=current_user,
            document_id=document_id,
            changelog_id=changelog_id,
            demo=demo,
        )
    except ValueError as exc:
        detail = str(exc)
        if detail == "document_not_found":
            raise HTTPException(status_code=404, detail="Document not found") from exc
        if detail == "changelog_not_found":
            raise HTTPException(status_code=404, detail="Changelog entry not found") from exc
        if detail == "changelog_already_reverted":
            raise HTTPException(
                status_code=409, detail="Changelog entry already reverted"
            ) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    record_document_updated(
        session, user=current_user, document=restored, usage=None, is_demo=demo
    )
    session.commit()
    session.refresh(restored)
    return build_v2_document_public(
        restored, session=session, actor=current_user, demo=demo
    )


@router.delete("/{document_id}", status_code=204)
def delete_v2_document(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> None:
    _maybe_seed_demo(session, current_user, demo)
    document = get_v2_document_for_actor(session, current_user, document_id, demo=demo)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    _require_document_owner(document, current_user)
    session.delete(document)
    session.commit()


@router.post(
    "/{document_id}/usage",
    response_model=MetricsUsageRecorded,
    status_code=202,
)
def record_v2_document_usage(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
    usage: TaskforceUsagePayload,
    demo: bool = Query(default=False),
) -> Any:
    """Record a Taskforce usage event without mutating the document body.

    Useful for the MCP layer to fire after every agent turn. Emits a
    tokens.consumed event plus any tokens.saved.* events the savings
    sources fired."""

    document = get_v2_document_for_actor(session, current_user, document_id, demo=demo)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not can_update_v2_document(session, document, current_user, demo=demo):
        raise HTTPException(
            status_code=403,
            detail="You do not have edit access to this document",
        )
    events = record_usage(
        session,
        user=current_user,
        document=document,
        usage=usage,
        is_demo=demo,
    )
    session.commit()
    for event in events:
        session.refresh(event)
    return _build_usage_response(events)


def _build_usage_response(events: list) -> MetricsUsageRecorded:  # type: ignore[type-arg]
    return MetricsUsageRecorded(
        events=[
            MetricsEventPublic(
                id=event.id,
                kind=event.kind,
                occurred_at=event.occurred_at,
                model_id=event.model_id,
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
                cache_read_tokens=event.cache_read_tokens,
                usd_amount=event.usd_amount,
            )
            for event in events
        ]
    )


@router.post(
    "/{document_id}/reused",
    response_model=MetricsUsageRecorded,
    status_code=202,
)
def record_v2_document_reused(
    session: SessionDep,
    current_user: CurrentUser,
    document_id: uuid.UUID,
    payload: TaskforceReusePayload,
    demo: bool = Query(default=False),
) -> Any:
    """Record a reuse decision made by the MCP scoring engine.

    Emits a document.reused event with score/band/reasons, plus a paired
    tokens.saved.reuse event sized at the doc's bootstrap_tokens estimate.
    If the agent also supplied a per-turn usage payload, the same events
    that POST /usage produces are appended."""

    document = get_v2_document_for_actor(session, current_user, document_id, demo=demo)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not can_update_v2_document(session, document, current_user, demo=demo):
        raise HTTPException(
            status_code=403,
            detail="You do not have edit access to this document",
        )
    events = record_document_reused(
        session,
        user=current_user,
        document=document,
        score=payload.score,
        band=payload.band,
        reasons=payload.reasons,
        usage=payload.usage,
        is_demo=demo,
        consumed_by_client=payload.client,
    )
    session.commit()
    for event in events:
        session.refresh(event)
    return _build_usage_response(events)
