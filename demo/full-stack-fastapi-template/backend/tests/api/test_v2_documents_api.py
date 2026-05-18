from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.v2_documents import DEMO_SEED
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _signup_and_activate(
    client: TestClient, db: Session
) -> tuple[str, dict[str, str]]:
    email = random_email()
    password = random_lower_string()

    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={
            "email": email,
            "password": password,
            "full_name": "V2 Documents Tester",
        },
    )
    assert 200 <= response.status_code < 300, response.text

    headers = user_authentication_headers(
        client=client, email=email, password=password
    )

    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    if not user.is_active:
        user.is_active = True
        db.add(user)
        db.commit()
        db.refresh(user)
    return email, headers


def test_v2_documents_list_seeds_demo_lazily(
    client: TestClient, db: Session
) -> None:
    _, headers = _signup_and_activate(client, db)

    # Without demo=true the user starts with zero documents.
    live = client.get("/api/v1/v2/documents/", headers=headers)
    assert live.status_code == 200, live.text
    assert live.json()["count"] == 0

    # First demo call lazily seeds the catalog.
    first = client.get("/api/v1/v2/documents/?demo=true", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["count"] == len(DEMO_SEED)
    titles = {doc["title"] for doc in first.json()["data"]}
    assert {seed["title"] for seed in DEMO_SEED} <= titles

    # Repeat call is idempotent — no duplicates.
    second = client.get("/api/v1/v2/documents/?demo=true", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["count"] == len(DEMO_SEED)


def test_v2_documents_create_update_get(client: TestClient, db: Session) -> None:
    _, headers = _signup_and_activate(client, db)

    created = client.post(
        "/api/v1/v2/documents/",
        headers=headers,
        json={
            "title": "Drafted document",
            "description": "Started in the library, fleshed out inline.",
            "human_summary": "Initial summary.",
            "collaborators": ["Tester"],
        },
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    assert created.json()["title"] == "Drafted document"
    assert created.json()["is_demo"] is False

    fetched = client.get(
        f"/api/v1/v2/documents/{document_id}", headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["description"] == (
        "Started in the library, fleshed out inline."
    )

    updated = client.patch(
        f"/api/v1/v2/documents/{document_id}",
        headers=headers,
        json={"human_summary": "Edited inline."},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["human_summary"] == "Edited inline."
    assert updated.json()["title"] == "Drafted document"

    empty_update = client.patch(
        f"/api/v1/v2/documents/{document_id}",
        headers=headers,
        json={},
    )
    assert empty_update.status_code == 422, empty_update.text


def test_v2_documents_are_scoped_to_owner(
    client: TestClient, db: Session
) -> None:
    _, owner_headers = _signup_and_activate(client, db)
    _, intruder_headers = _signup_and_activate(client, db)

    created = client.post(
        "/api/v1/v2/documents/",
        headers=owner_headers,
        json={"title": "Owner-only document"},
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]

    forbidden = client.get(
        f"/api/v1/v2/documents/{document_id}", headers=intruder_headers
    )
    assert forbidden.status_code == 404, forbidden.text

    intruder_patch = client.patch(
        f"/api/v1/v2/documents/{document_id}",
        headers=intruder_headers,
        json={"title": "Hijacked"},
    )
    assert intruder_patch.status_code == 404, intruder_patch.text
