import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import func, select

from app.api.deps import (
    ActiveUser,
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from app.models import (
    Organization,
    OrganizationCreate,
    OrganizationInvitation,
    OrganizationInvitationCreate,
    OrganizationInvitationPublic,
    OrganizationInvitationsPublic,
    OrganizationMemberPublic,
    OrganizationMemberUpdate,
    OrganizationMePublic,
    OrganizationPublic,
    OrganizationsPublic,
    OrganizationUpdate,
    User,
    get_datetime_utc,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _normalized_email(email: str) -> str:
    return email.strip().lower()


def _get_organization_or_404(session: SessionDep, organization_id: uuid.UUID) -> Organization:
    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


def _ensure_unique_name(
    session: SessionDep, name: str, *, organization_id: uuid.UUID | None = None
) -> None:
    existing = session.exec(
        select(Organization).where(Organization.name == name.strip())
    ).first()
    if existing and existing.id != organization_id:
        raise HTTPException(
            status_code=409,
            detail="Organization with this name already exists",
        )


def _require_current_organization(
    session: SessionDep, current_user: CurrentUser
) -> Organization:
    if current_user.organization_id is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _get_organization_or_404(session, current_user.organization_id)


def _require_current_org_admin(
    session: SessionDep, current_user: ActiveUser
) -> Organization:
    organization = _require_current_organization(session, current_user)
    if not current_user.is_superuser and current_user.organization_role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only organization admins can perform this action",
        )
    return organization


def _member_public(user: User) -> OrganizationMemberPublic:
    return OrganizationMemberPublic(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        organization_role=user.organization_role,
    )


def _pending_invites_for_org(
    session: SessionDep, organization_id: uuid.UUID
) -> list[OrganizationInvitation]:
    statement = (
        select(OrganizationInvitation)
        .where(OrganizationInvitation.organization_id == organization_id)
        .where(OrganizationInvitation.accepted_at.is_(None))  # type: ignore[union-attr]
        .where(OrganizationInvitation.revoked_at.is_(None))  # type: ignore[union-attr]
        .order_by(OrganizationInvitation.created_at.desc())
    )
    return list(session.exec(statement).all())


def _count_admins(session: SessionDep, organization_id: uuid.UUID) -> int:
    statement = (
        select(func.count())
        .select_from(User)
        .where(User.organization_id == organization_id)
        .where(User.organization_role == "admin")
    )
    return session.exec(statement).one()


@router.get(
    "/me",
    response_model=OrganizationMePublic,
)
def read_my_organization(session: SessionDep, current_user: CurrentUser) -> Any:
    organization = _require_current_organization(session, current_user)
    members = session.exec(
        select(User)
        .where(User.organization_id == organization.id)
        .order_by(User.email)
    ).all()
    invitations = _pending_invites_for_org(session, organization.id)
    return OrganizationMePublic(
        id=organization.id,
        name=organization.name,
        created_at=organization.created_at,
        updated_at=organization.updated_at,
        organization_role=current_user.organization_role,
        members=[_member_public(member) for member in members],
        invitations=[
            OrganizationInvitationPublic.model_validate(
                invitation, from_attributes=True
            )
            for invitation in invitations
        ],
    )


@router.post(
    "/invitations",
    response_model=OrganizationInvitationPublic,
    status_code=201,
)
def create_organization_invitation(
    *,
    session: SessionDep,
    invitation_in: OrganizationInvitationCreate,
    current_user: ActiveUser,
) -> Any:
    organization = _require_current_org_admin(session, current_user)
    invited_email = _normalized_email(invitation_in.email)
    existing_user = session.exec(
        select(User).where(User.email == invited_email)
    ).first()
    if existing_user and existing_user.organization_id == organization.id:
        raise HTTPException(
            status_code=409,
            detail="User already belongs to this organization",
        )

    existing_invitation = session.exec(
        select(OrganizationInvitation)
        .where(OrganizationInvitation.organization_id == organization.id)
        .where(OrganizationInvitation.invited_email == invited_email)
        .where(OrganizationInvitation.accepted_at.is_(None))  # type: ignore[union-attr]
        .where(OrganizationInvitation.revoked_at.is_(None))  # type: ignore[union-attr]
    ).first()
    if existing_invitation:
        return existing_invitation

    invitation = OrganizationInvitation(
        organization_id=organization.id,
        invited_email=invited_email,
        invited_by_user_id=current_user.id,
    )
    session.add(invitation)
    session.commit()
    session.refresh(invitation)
    return invitation


@router.get(
    "/invitations",
    response_model=OrganizationInvitationsPublic,
)
def read_my_organization_invitations(
    session: SessionDep, current_user: CurrentUser
) -> Any:
    invited_email = _normalized_email(current_user.email)
    invitations = session.exec(
        select(OrganizationInvitation)
        .where(OrganizationInvitation.invited_email == invited_email)
        .where(OrganizationInvitation.accepted_at.is_(None))  # type: ignore[union-attr]
        .where(OrganizationInvitation.revoked_at.is_(None))  # type: ignore[union-attr]
        .order_by(OrganizationInvitation.created_at.desc())
    ).all()
    return OrganizationInvitationsPublic(
        data=[
            OrganizationInvitationPublic.model_validate(
                invitation, from_attributes=True
            )
            for invitation in invitations
        ],
        count=len(invitations),
    )


@router.post(
    "/invitations/{invitation_id}/accept",
    response_model=OrganizationMePublic,
)
def accept_organization_invitation(
    *,
    session: SessionDep,
    invitation_id: uuid.UUID,
    current_user: ActiveUser,
) -> Any:
    invitation = session.get(OrganizationInvitation, invitation_id)
    if (
        not invitation
        or invitation.revoked_at is not None
        or invitation.accepted_at is not None
        or _normalized_email(invitation.invited_email)
        != _normalized_email(current_user.email)
    ):
        raise HTTPException(status_code=404, detail="Invitation not found")

    organization = _get_organization_or_404(session, invitation.organization_id)
    invitation.accepted_at = get_datetime_utc()
    current_user.organization_id = organization.id
    current_user.organization_role = "member"
    session.add(invitation)
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    session.refresh(organization)
    return read_my_organization(session, current_user)


@router.patch(
    "/members/{user_id}",
    response_model=OrganizationMemberPublic,
)
def update_organization_member(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    member_in: OrganizationMemberUpdate,
    current_user: ActiveUser,
) -> Any:
    organization = _require_current_org_admin(session, current_user)
    member = session.get(User, user_id)
    if not member or member.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Organization member not found")

    if (
        member.organization_role == "admin"
        and member_in.organization_role == "member"
        and _count_admins(session, organization.id) <= 1
    ):
        raise HTTPException(
            status_code=422,
            detail="Organization must have at least one admin",
        )

    member.organization_role = member_in.organization_role
    session.add(member)
    session.commit()
    session.refresh(member)
    return _member_public(member)


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=OrganizationsPublic,
)
def read_organizations(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    count_statement = select(func.count()).select_from(Organization)
    count = session.exec(count_statement).one()
    statement = (
        select(Organization).order_by(Organization.name).offset(skip).limit(limit)
    )
    organizations = session.exec(statement).all()
    return OrganizationsPublic(data=organizations, count=count)


@router.post(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=OrganizationPublic,
    status_code=201,
)
def create_organization(
    *, session: SessionDep, organization_in: OrganizationCreate
) -> Any:
    name = organization_in.name.strip()
    _ensure_unique_name(session, name)
    organization = Organization(name=name)
    session.add(organization)
    session.commit()
    session.refresh(organization)
    return organization


@router.get(
    "/{organization_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=OrganizationPublic,
)
def read_organization(session: SessionDep, organization_id: uuid.UUID) -> Any:
    return _get_organization_or_404(session, organization_id)


@router.patch(
    "/{organization_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=OrganizationPublic,
)
def update_organization(
    *,
    session: SessionDep,
    organization_id: uuid.UUID,
    organization_in: OrganizationUpdate,
) -> Any:
    organization = _get_organization_or_404(session, organization_id)
    update = organization_in.model_dump(exclude_unset=True)
    if "name" in update:
        name = update["name"].strip()
        _ensure_unique_name(session, name, organization_id=organization_id)
        organization.name = name
    organization.updated_at = get_datetime_utc()
    session.add(organization)
    session.commit()
    session.refresh(organization)
    return organization
