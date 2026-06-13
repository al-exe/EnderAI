from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import METRICS_EVENT_TOKENS_SAVED_CACHE, MetricsEvent, User
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _signup(
    client: TestClient,
    db: Session,
    *,
    full_name: str,
) -> tuple[User, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert 200 <= response.status_code < 300, response.text

    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    headers = user_authentication_headers(
        client=client,
        email=email,
        password=password,
    )
    return user, headers


def _tokens_saved_event(db: Session, user: User, tokens: int) -> None:
    db.add(
        MetricsEvent(
            occurred_at=datetime.now(timezone.utc),
            user_id=user.id,
            organization_id=user.organization_id,
            kind=METRICS_EVENT_TOKENS_SAVED_CACHE,
            input_tokens=tokens,
            payload={},
            is_demo=False,
        )
    )
    db.commit()


def _tokens_saved(
    client: TestClient,
    headers: dict[str, str],
    *,
    scope: str,
) -> tuple[int, str]:
    response = client.get(
        f"{settings.API_V1_STR}/v2/metrics",
        headers=headers,
        params={
            "window": "7d",
            "metrics": "tokens_saved",
            "scope": scope,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return int(body["metrics"]["tokens_saved"]["total"]), body["scope"]


def test_org_admin_metrics_include_all_members_but_not_outsiders(
    client: TestClient,
    db: Session,
) -> None:
    admin, admin_headers = _signup(client, db, full_name="Metrics Admin")
    member, member_headers = _signup(client, db, full_name="Metrics Member")
    outsider, _ = _signup(client, db, full_name="Metrics Outsider")
    assert admin.organization_id is not None

    member.organization_id = admin.organization_id
    member.organization_role = "member"
    db.add(member)
    db.commit()
    db.refresh(member)

    _tokens_saved_event(db, admin, 100)
    _tokens_saved_event(db, member, 250)
    _tokens_saved_event(db, outsider, 999)

    personal_total, personal_scope = _tokens_saved(
        client, admin_headers, scope="personal"
    )
    organization_total, organization_scope = _tokens_saved(
        client, admin_headers, scope="organization"
    )

    assert personal_total == 100
    assert personal_scope == "personal"
    assert organization_total == 350
    assert organization_scope == "organization"

    member_response = client.get(
        f"{settings.API_V1_STR}/v2/metrics",
        headers=member_headers,
        params={"metrics": "tokens_saved", "scope": "organization"},
    )
    assert member_response.status_code == 403


def test_solo_org_admin_metrics_match_personal_scope(
    client: TestClient,
    db: Session,
) -> None:
    admin, headers = _signup(client, db, full_name="Solo Metrics Admin")
    _tokens_saved_event(db, admin, 420)

    personal_total, _ = _tokens_saved(client, headers, scope="personal")
    organization_total, _ = _tokens_saved(client, headers, scope="organization")

    assert personal_total == organization_total == 420
