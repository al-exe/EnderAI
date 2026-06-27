from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import UserCreate
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _signup_and_login(client: TestClient) -> tuple[str, dict[str, str]]:
    email = random_email()
    password = random_lower_string()

    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={
            "email": email,
            "password": password,
            "full_name": "Demo Mode Tester",
        },
    )
    assert 200 <= response.status_code < 300, response.text

    headers = user_authentication_headers(
        client=client,
        email=email,
        password=password,
    )
    return email, headers


def test_demo_mode_keeps_v1_surfaces_empty(
    client: TestClient,
    db: Session,
) -> None:
    """The demo is V2-only: toggling demo mode must not seed V1 topics/cases."""
    email, headers = _signup_and_login(client)
    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    assert user.demo_seeded_at is not None

    for path in ("/api/v1/topics/", "/api/v1/cases/"):
        live = client.get(path, headers=headers)
        assert live.status_code == 200, live.text
        assert live.json()["count"] == 0

        demo = client.get(path, headers=headers, params={"demo": True})
        assert demo.status_code == 200, demo.text
        assert demo.json()["count"] == 0


def test_demo_mode_seeds_and_filters_v2_documents(
    client: TestClient,
) -> None:
    """Demo mode lazily clones the V2 document catalog and isolates it from
    the live workspace (and vice versa)."""
    _email, headers = _signup_and_login(client)

    # No live documents yet.
    live_empty = client.get("/api/v1/v2/documents/", headers=headers)
    assert live_empty.status_code == 200, live_empty.text
    assert live_empty.json()["count"] == 0

    # A live document is created outside demo mode and stays out of it.
    live_doc = client.post(
        "/api/v1/v2/documents/",
        headers=headers,
        json={
            "title": "Live workspace document",
            "description": "This document should only appear outside demo mode.",
        },
    )
    assert live_doc.status_code == 201, live_doc.text
    live_doc_body = live_doc.json()
    live_doc_id = live_doc_body["id"]
    assert live_doc_body["is_demo"] is False

    live_list = client.get("/api/v1/v2/documents/", headers=headers)
    assert live_list.status_code == 200, live_list.text
    assert [row["id"] for row in live_list.json()["data"]] == [live_doc_id]

    # Demo mode lazily seeds the demo catalog; every row is is_demo and the
    # live document is not visible.
    demo_list = client.get(
        "/api/v1/v2/documents/", headers=headers, params={"demo": True}
    )
    assert demo_list.status_code == 200, demo_list.text
    demo_body = demo_list.json()
    assert demo_body["count"] > 0
    assert all(row["is_demo"] is True for row in demo_body["data"])
    assert all(row["id"] != live_doc_id for row in demo_body["data"])

    # A demo document is hidden without the demo flag and visible with it.
    demo_doc_id = demo_body["data"][0]["id"]
    hidden = client.get(f"/api/v1/v2/documents/{demo_doc_id}", headers=headers)
    assert hidden.status_code == 404, hidden.text

    visible = client.get(
        f"/api/v1/v2/documents/{demo_doc_id}",
        headers=headers,
        params={"demo": True},
    )
    assert visible.status_code == 200, visible.text

    # And the live document is unaffected by demo seeding.
    live_again = client.get(f"/api/v1/v2/documents/{live_doc_id}", headers=headers)
    assert live_again.status_code == 200, live_again.text
    assert live_again.json()["is_demo"] is False


def test_demo_mode_marks_existing_users_without_v1_seed(
    client: TestClient,
    db: Session,
) -> None:
    email = random_email()
    password = random_lower_string()
    crud.create_user(
        session=db,
        user_create=UserCreate(email=email, password=password),
    )
    headers = user_authentication_headers(
        client=client,
        email=email,
        password=password,
    )

    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    assert user.demo_seeded_at is None

    # Hitting a V1 route with demo=True marks the account demo-seeded but seeds
    # no V1 rows (V2-only demo).
    response = client.get(
        "/api/v1/topics/",
        headers=headers,
        params={"demo": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 0

    db.refresh(user)
    assert user.demo_seeded_at is not None
