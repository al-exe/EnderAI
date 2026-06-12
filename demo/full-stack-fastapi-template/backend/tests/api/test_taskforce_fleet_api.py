"""Integration coverage for the Taskforce Fleet control-panel API."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import TaskforceFleetSession, TaskforceSessionArchive, User, V2Document
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _signup(client: TestClient) -> tuple[str, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={"email": email, "password": password, "full_name": "Fleet Tester"},
    )
    assert 200 <= response.status_code < 300, response.text
    return email, user_authentication_headers(
        client=client,
        email=email,
        password=password,
    )


def _user_by_email(db: Session, email: str) -> User:
    return db.exec(select(User).where(User.email == email)).one()


def _create_archive(
    db: Session,
    *,
    user: User,
    session_id: str,
    imported_at: datetime,
    ended_at: datetime | None = None,
    fleet_session_id: uuid.UUID | None = None,
    referenced_document_ids: list[str] | None = None,
    model_id: str | None = "claude-opus-4-8",
) -> TaskforceSessionArchive:
    archive = TaskforceSessionArchive(
        session_id=session_id,
        actor_id=user.id,
        organization_id=user.organization_id,
        repo="EnderAI",
        branch=f"feature/{session_id}",
        cwd="/workspace/EnderAI",
        title=f"Archive {session_id}",
        specialist_slug="backend",
        model_id=model_id,
        imported_at=imported_at,
        last_seen_at=imported_at,
        ended_at=ended_at,
        fleet_session_id=fleet_session_id,
        referenced_document_ids=referenced_document_ids or [],
    )
    db.add(archive)
    db.commit()
    db.refresh(archive)
    return archive


def _create_fleet(
    client: TestClient,
    headers: dict[str, str],
    name: str,
) -> dict[str, object]:
    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/fleet",
        headers=headers,
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_fleet_session_crud_is_actor_scoped(
    client: TestClient,
    db: Session,
) -> None:
    _, owner_headers = _signup(client)
    _, other_headers = _signup(client)
    fleet = _create_fleet(client, owner_headers, "Checkout sprint")

    renamed = client.patch(
        f"{settings.API_V1_STR}/v2/taskforce/fleet/{fleet['id']}",
        headers=owner_headers,
        json={"name": "Checkout launch"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Checkout launch"

    hidden = client.patch(
        f"{settings.API_V1_STR}/v2/taskforce/fleet/{fleet['id']}",
        headers=other_headers,
        json={"name": "Not mine"},
    )
    assert hidden.status_code == 404

    deleted = client.delete(
        f"{settings.API_V1_STR}/v2/taskforce/fleet/{fleet['id']}",
        headers=owner_headers,
    )
    assert deleted.status_code == 204, deleted.text
    assert db.get(TaskforceFleetSession, uuid.UUID(str(fleet["id"]))) is None


def test_fleet_groups_top_five_recent_active_sessions(
    client: TestClient,
    db: Session,
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    fleet = _create_fleet(client, headers, "Fleet alpha")
    fleet_id = uuid.UUID(str(fleet["id"]))
    now = datetime.now(timezone.utc)

    document = V2Document(
        owner_id=user.id,
        organization_id=user.organization_id,
        title="Fleet document",
        ai_generated_summary="The agent implemented the Fleet backend.",
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    for index in range(6):
        _create_archive(
            db,
            user=user,
            session_id=f"recent-{index}",
            imported_at=now - timedelta(minutes=index),
            fleet_session_id=fleet_id if index < 2 else None,
            referenced_document_ids=[str(document.id)] if index == 0 else None,
        )
    _create_archive(
        db,
        user=user,
        session_id="too-old",
        imported_at=now - timedelta(hours=9),
    )
    _create_archive(
        db,
        user=user,
        session_id="ended",
        imported_at=now,
        ended_at=now,
    )

    response = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/fleet",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    grouped = next(
        item for item in body["fleet_sessions"] if item["id"] == str(fleet_id)
    )
    grouped_ids = [agent["session_id"] for agent in grouped["agents"]]
    unassigned_ids = [agent["session_id"] for agent in body["unassigned"]]

    assert grouped_ids == ["recent-0", "recent-1"]
    assert unassigned_ids == ["recent-2", "recent-3", "recent-4"]
    assert "recent-5" not in grouped_ids + unassigned_ids
    assert "too-old" not in grouped_ids + unassigned_ids
    assert "ended" not in grouped_ids + unassigned_ids
    assert grouped["agents"][0]["active_document_id"] == str(document.id)
    assert grouped["agents"][0]["title"] == "Fleet document"
    assert "implemented the Fleet backend" in grouped["agents"][0]["summary_markdown"]
    assert grouped["agents"][0]["model_id"] == "claude-opus-4-8"


def test_assign_unassign_and_delete_never_end_session(
    client: TestClient,
    db: Session,
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    fleet = _create_fleet(client, headers, "Mutable Fleet")
    fleet_id = uuid.UUID(str(fleet["id"]))
    archive = _create_archive(
        db,
        user=user,
        session_id="assignable",
        imported_at=datetime.now(timezone.utc),
    )

    assigned = client.patch(
        f"{settings.API_V1_STR}/v2/taskforce/session/{archive.session_id}",
        headers=headers,
        json={"fleet_session_id": str(fleet_id)},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["fleet_session_id"] == str(fleet_id)
    db.refresh(archive)
    assert archive.fleet_session_id == fleet_id
    assert archive.ended_at is None

    unassigned = client.patch(
        f"{settings.API_V1_STR}/v2/taskforce/session/{archive.session_id}",
        headers=headers,
        json={"fleet_session_id": None},
    )
    assert unassigned.status_code == 200, unassigned.text
    assert unassigned.json()["fleet_session_id"] is None
    db.refresh(archive)
    assert archive.fleet_session_id is None
    assert archive.ended_at is None

    archive.fleet_session_id = fleet_id
    db.add(archive)
    db.commit()
    deleted = client.delete(
        f"{settings.API_V1_STR}/v2/taskforce/fleet/{fleet_id}",
        headers=headers,
    )
    assert deleted.status_code == 204, deleted.text
    db.refresh(archive)
    assert archive.fleet_session_id is None
    assert archive.ended_at is None


def test_assignment_rejects_another_actors_fleet(
    client: TestClient,
    db: Session,
) -> None:
    owner_email, owner_headers = _signup(client)
    _, other_headers = _signup(client)
    owner = _user_by_email(db, owner_email)
    other_fleet = _create_fleet(client, other_headers, "Other Fleet")
    archive = _create_archive(
        db,
        user=owner,
        session_id="owner-session",
        imported_at=datetime.now(timezone.utc),
    )

    response = client.patch(
        f"{settings.API_V1_STR}/v2/taskforce/session/{archive.session_id}",
        headers=owner_headers,
        json={"fleet_session_id": other_fleet["id"]},
    )
    assert response.status_code == 404
    db.refresh(archive)
    assert archive.fleet_session_id is None
    assert archive.ended_at is None
