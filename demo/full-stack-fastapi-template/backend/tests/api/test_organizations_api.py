from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _signup_and_activate(
    client: TestClient, db: Session, *, full_name: str
) -> tuple[str, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert 200 <= response.status_code < 300, response.text

    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    user.is_active = True
    db.add(user)
    db.commit()
    db.refresh(user)

    headers = user_authentication_headers(
        client=client, email=email, password=password
    )
    return email, headers


def test_signup_creates_personal_org_with_admin_role(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup_and_activate(client, db, full_name="Personal Org User")
    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    assert user.organization_id is not None
    assert user.organization_role == "admin"

    organization = client.get("/api/v1/organizations/me", headers=headers)
    assert organization.status_code == 200, organization.text
    assert organization.json()["id"] == str(user.organization_id)
    assert organization.json()["organization_role"] == "admin"
    assert [member["email"] for member in organization.json()["members"]] == [email]


def test_org_admin_can_invite_and_member_accepts_as_regular_member(
    client: TestClient, db: Session
) -> None:
    admin_email, admin_headers = _signup_and_activate(
        client, db, full_name="Org Admin"
    )
    member_email, member_headers = _signup_and_activate(
        client, db, full_name="Org Member"
    )
    admin = crud.get_user_by_email(session=db, email=admin_email)
    member = crud.get_user_by_email(session=db, email=member_email)
    assert admin is not None
    assert member is not None
    assert admin.organization_id != member.organization_id

    invite = client.post(
        "/api/v1/organizations/invitations",
        headers=admin_headers,
        json={"email": member_email.upper()},
    )
    assert invite.status_code == 201, invite.text
    assert invite.json()["organization_id"] == str(admin.organization_id)
    assert invite.json()["invited_email"] == member_email

    pending = client.get("/api/v1/organizations/invitations", headers=member_headers)
    assert pending.status_code == 200, pending.text
    assert pending.json()["count"] == 1
    assert pending.json()["data"][0]["id"] == invite.json()["id"]

    accepted = client.post(
        f"/api/v1/organizations/invitations/{invite.json()['id']}/accept",
        headers=member_headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["id"] == str(admin.organization_id)
    assert accepted.json()["organization_role"] == "member"

    db.refresh(member)
    assert member.organization_id == admin.organization_id
    assert member.organization_role == "member"


def test_org_admin_can_promote_members_and_members_cannot_invite(
    client: TestClient, db: Session
) -> None:
    admin_email, admin_headers = _signup_and_activate(
        client, db, full_name="Promoter"
    )
    member_email, member_headers = _signup_and_activate(
        client, db, full_name="Promotee"
    )
    admin = crud.get_user_by_email(session=db, email=admin_email)
    member = crud.get_user_by_email(session=db, email=member_email)
    assert admin is not None
    assert member is not None

    invite = client.post(
        "/api/v1/organizations/invitations",
        headers=admin_headers,
        json={"email": member_email},
    )
    assert invite.status_code == 201, invite.text
    accepted = client.post(
        f"/api/v1/organizations/invitations/{invite.json()['id']}/accept",
        headers=member_headers,
    )
    assert accepted.status_code == 200, accepted.text

    blocked_invite = client.post(
        "/api/v1/organizations/invitations",
        headers=member_headers,
        json={"email": random_email()},
    )
    assert blocked_invite.status_code == 403, blocked_invite.text

    promoted = client.patch(
        f"/api/v1/organizations/members/{member.id}",
        headers=admin_headers,
        json={"organization_role": "admin"},
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["organization_role"] == "admin"

    allowed_invite = client.post(
        "/api/v1/organizations/invitations",
        headers=member_headers,
        json={"email": random_email()},
    )
    assert allowed_invite.status_code == 201, allowed_invite.text
