"""Integration coverage for the Taskforce Fleet control-panel API."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.taskforce.active_sessions import _fleet_status
from app.models import (
    AgentSpecialist,
    TaskforceFleetSession,
    TaskforceSessionArchive,
    User,
    V2Document,
)
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
    started_at: datetime | None = None,
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
        started_at=started_at,
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
    name: str | None = None,
) -> dict[str, object]:
    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/fleet",
        headers=headers,
        json={},
    )
    assert response.status_code == 201, response.text
    fleet = response.json()
    if name is None:
        return fleet
    renamed = client.patch(
        f"{settings.API_V1_STR}/v2/taskforce/fleet/{fleet['id']}",
        headers=headers,
        json={"name": name},
    )
    assert renamed.status_code == 200, renamed.text
    return renamed.json()


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
    specialist = AgentSpecialist(
        owner_id=user.id,
        organization_id=user.organization_id,
        slug=f"backend-{random_lower_string()}",
        name="Backend",
        role="Backend implementation",
        short_description="Backend implementation conventions",
        instructions=[
            "Keep actor-scoped queries explicit.",
            "Cover public response contracts with integration tests.",
        ],
    )
    db.add(specialist)
    db.commit()
    db.refresh(specialist)

    for index in range(6):
        archive = _create_archive(
            db,
            user=user,
            session_id=f"recent-{index}",
            imported_at=now - timedelta(minutes=index * 2),
            started_at=now - timedelta(hours=1, minutes=index),
            fleet_session_id=fleet_id,
            referenced_document_ids=[str(document.id)] if index == 0 else None,
        )
        archive.specialist_slug = specialist.slug
        db.add(archive)
    db.commit()
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

    assert "unassigned" not in body
    assert grouped_ids == [
        "recent-0",
        "recent-1",
        "recent-2",
    ]
    assert "recent-3" not in grouped_ids
    assert "recent-4" not in grouped_ids
    history = next(item for item in body["fleet_sessions"] if item["is_history"])
    history_ids = {agent["session_id"] for agent in history["agents"]}
    assert {"recent-3", "recent-4"}.issubset(history_ids)
    assert "too-old" not in grouped_ids
    assert "ended" not in grouped_ids
    assert grouped["agents"][0]["active_document_id"] == str(document.id)
    assert grouped["agents"][0]["title"] == "Fleet document"
    assert "implemented the Fleet backend" in grouped["agents"][0]["summary_markdown"]
    assert grouped["agents"][0]["model_id"] == "claude-opus-4-8"
    assert grouped["agents"][0]["status"] == "running"
    assert datetime.fromisoformat(
        grouped["agents"][0]["started_at"].replace("Z", "+00:00")
    ) == now - timedelta(hours=1)
    assert grouped["agents"][0]["specialist_rule_count"] == 2
    assert grouped["agents"][1]["status"] == "running"
    assert grouped["agents"][2]["status"] == "running"
    assert "recent-5" not in grouped_ids


def test_reassign_and_delete_move_agent_without_ending_session(
    client: TestClient,
    db: Session,
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    default_fleet = _create_fleet(client, headers)
    destination = _create_fleet(client, headers)
    default_fleet_id = uuid.UUID(str(default_fleet["id"]))
    destination_id = uuid.UUID(str(destination["id"]))
    archive = _create_archive(
        db,
        user=user,
        session_id="assignable",
        imported_at=datetime.now(timezone.utc),
        fleet_session_id=default_fleet_id,
    )

    assigned = client.patch(
        f"{settings.API_V1_STR}/v2/taskforce/session/{archive.session_id}",
        headers=headers,
        json={"fleet_session_id": str(destination_id)},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["fleet_session_id"] == str(destination_id)
    db.refresh(archive)
    assert archive.fleet_session_id == destination_id
    assert archive.ended_at is None

    unassigned = client.patch(
        f"{settings.API_V1_STR}/v2/taskforce/session/{archive.session_id}",
        headers=headers,
        json={"fleet_session_id": None},
    )
    assert unassigned.status_code == 422, unassigned.text
    db.refresh(archive)
    assert archive.fleet_session_id == destination_id
    assert archive.ended_at is None

    deleted = client.delete(
        f"{settings.API_V1_STR}/v2/taskforce/fleet/{destination_id}",
        headers=headers,
    )
    assert deleted.status_code == 204, deleted.text
    db.refresh(archive)
    assert archive.fleet_session_id == default_fleet_id
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


def test_first_agent_gets_session_one_and_provisional_current_work(
    client: TestClient,
    db: Session,
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)

    discover = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "Implement the fleet session defaults",
            "session_id": "default-session-agent",
            "min_score": 0.0,
        },
    )
    assert discover.status_code == 200, discover.text

    archive = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.actor_id == user.id,
            TaskforceSessionArchive.session_id == "default-session-agent",
        )
    ).one()
    fleet_session = db.get(TaskforceFleetSession, archive.fleet_session_id)
    assert fleet_session is not None
    assert fleet_session.name == "Session 1"

    fleet = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/fleet",
        headers=headers,
    )
    assert fleet.status_code == 200, fleet.text
    body = fleet.json()
    assert "unassigned" not in body
    default_fleet = next(
        item for item in body["fleet_sessions"] if not item["is_history"]
    )
    agent = default_fleet["agents"][0]
    assert agent["session_id"] == "default-session-agent"
    assert agent["display_name"] == "Implementing the fleet session defaults"
    assert agent["summary_markdown"] == ""


def test_codex_session_heartbeat_creates_fleet_agent_before_first_prompt(
    client: TestClient,
    db: Session,
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/session/heartbeat",
        headers=headers,
        json={
            "session_id": "codex-startup-session",
            "cwd": "/workspace/EnderAI",
            "git_branch": "feature/codex-fleet",
            "client": "codex",
            "model_id": "gpt-5.4",
            "source": "startup",
        },
    )
    assert response.status_code == 204, response.text

    archive = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.actor_id == user.id,
            TaskforceSessionArchive.session_id == "codex-startup-session",
        )
    ).one()
    assert archive.client == "codex"
    assert archive.model_id == "gpt-5.4"
    assert archive.repo == "EnderAI"
    assert archive.title is None
    assert archive.fleet_session_id is not None

    fleet = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/fleet",
        headers=headers,
    )
    assert fleet.status_code == 200, fleet.text
    agents = [
        agent for item in fleet.json()["fleet_sessions"] for agent in item["agents"]
    ]
    agent = next(
        item for item in agents if item["session_id"] == "codex-startup-session"
    )
    assert agent["model_id"] == "gpt-5.4"
    assert agent["display_name"] == "GPT 5.4"
    assert agent["summary_markdown"] == ""


def _agent_in_fleet(
    client: TestClient, headers: dict[str, str], session_id: str
) -> dict[str, object]:
    fleet = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/fleet",
        headers=headers,
    )
    assert fleet.status_code == 200, fleet.text
    agents = [
        agent for item in fleet.json()["fleet_sessions"] for agent in item["agents"]
    ]
    return next(item for item in agents if item["session_id"] == session_id)


def test_fleet_status_distinguishes_running_waiting_idle() -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)

    # A prompt arrived after the last turn end → a turn is in progress.
    assert (
        _fleet_status(
            1,
            last_seen_at=now,
            last_turn_ended_at=now - timedelta(minutes=2),
        )
        == "running"
    )
    # The turn ended at/after the last prompt → awaiting the next user prompt.
    assert (
        _fleet_status(
            1,
            last_seen_at=now - timedelta(minutes=1),
            last_turn_ended_at=now,
        )
        == "waiting"
    )
    # No turn-end recorded yet but fresh → running.
    assert _fleet_status(1, last_seen_at=now, last_turn_ended_at=None) == "running"
    # Stale beyond the live window → idle regardless of turn state.
    assert _fleet_status(120, last_seen_at=now, last_turn_ended_at=now) == "idle"


def test_session_turn_ended_marks_agent_awaiting_prompt(
    client: TestClient,
) -> None:
    _, headers = _signup(client)

    # A fresh prompt registers the session as running.
    discover = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "Wire up the fleet turn state",
            "session_id": "turn-state-session",
            "min_score": 0.0,
        },
    )
    assert discover.status_code == 200, discover.text
    assert _agent_in_fleet(client, headers, "turn-state-session")["status"] == "running"

    # The Stop hook fires: the agent finished its turn and awaits a prompt.
    turn_ended = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/session/turn-ended",
        headers=headers,
        json={"session_id": "turn-state-session"},
    )
    assert turn_ended.status_code == 204, turn_ended.text
    assert _agent_in_fleet(client, headers, "turn-state-session")["status"] == "waiting"

    # A new prompt flips it back to running.
    discover_again = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "Keep going",
            "session_id": "turn-state-session",
            "min_score": 0.0,
        },
    )
    assert discover_again.status_code == 200, discover_again.text
    assert _agent_in_fleet(client, headers, "turn-state-session")["status"] == "running"


def test_session_turn_ended_is_noop_without_archive(client: TestClient) -> None:
    _, headers = _signup(client)
    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/session/turn-ended",
        headers=headers,
        json={"session_id": "never-seen-session"},
    )
    assert response.status_code == 204, response.text


def test_fleet_agent_display_name_can_be_renamed(
    client: TestClient,
    db: Session,
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)

    discover = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "Implement the fleet session defaults",
            "session_id": "renameable-session",
            "min_score": 0.0,
        },
    )
    assert discover.status_code == 200, discover.text

    renamed = client.patch(
        f"{settings.API_V1_STR}/v2/taskforce/session/renameable-session",
        headers=headers,
        json={"display_name": "Fleet defaults rollout"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["display_name"] == "Fleet defaults rollout"

    archive = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.actor_id == user.id,
            TaskforceSessionArchive.session_id == "renameable-session",
        )
    ).one()
    assert archive.display_name == "Fleet defaults rollout"
    assert archive.conversation_summary == "Implementing the fleet session defaults"


def test_new_fleet_sessions_are_auto_named(
    client: TestClient,
) -> None:
    _, headers = _signup(client)

    first = _create_fleet(client, headers)
    second = _create_fleet(client, headers)

    assert first["name"] == "Session 1"
    assert second["name"] == "Session 2"


def test_discovery_document_pool_flips_after_agent_reassignment(
    client: TestClient,
    db: Session,
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    session_id = "pool-flip-agent"

    initial_discover = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "shared pool sentinel",
            "session_id": session_id,
            "min_score": 0.0,
        },
    )
    assert initial_discover.status_code == 200, initial_discover.text
    archive = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.actor_id == user.id,
            TaskforceSessionArchive.session_id == session_id,
        )
    ).one()
    original_fleet_id = archive.fleet_session_id
    destination = _create_fleet(client, headers)
    destination_id = uuid.UUID(str(destination["id"]))

    original_doc = V2Document(
        owner_id=user.id,
        organization_id=user.organization_id,
        title="Original pool document",
        description="shared pool sentinel",
        fleet_session_id=original_fleet_id,
    )
    destination_doc = V2Document(
        owner_id=user.id,
        organization_id=user.organization_id,
        title="Destination pool document",
        description="shared pool sentinel",
        fleet_session_id=destination_id,
    )
    global_doc = V2Document(
        owner_id=user.id,
        organization_id=user.organization_id,
        title="Global pool document",
        description="shared pool sentinel",
        fleet_session_id=None,
    )
    db.add_all([original_doc, destination_doc, global_doc])
    db.commit()
    for document in (original_doc, destination_doc, global_doc):
        db.refresh(document)

    before = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "shared pool sentinel",
            "session_id": session_id,
            "k": 3,
            "min_score": 0.0,
        },
    )
    assert before.status_code == 200, before.text
    before_ids = {match["document_id"] for match in before.json()["matches"]}
    assert str(original_doc.id) in before_ids
    assert str(global_doc.id) in before_ids
    assert str(destination_doc.id) not in before_ids

    reassigned = client.patch(
        f"{settings.API_V1_STR}/v2/taskforce/session/{session_id}",
        headers=headers,
        json={"fleet_session_id": str(destination_id)},
    )
    assert reassigned.status_code == 200, reassigned.text

    after = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "shared pool sentinel",
            "session_id": session_id,
            "k": 3,
            "min_score": 0.0,
        },
    )
    assert after.status_code == 200, after.text
    after_ids = {match["document_id"] for match in after.json()["matches"]}
    assert str(destination_doc.id) in after_ids
    assert str(global_doc.id) in after_ids
    assert str(original_doc.id) not in after_ids

    db.refresh(original_doc)
    assert original_doc.fleet_session_id == original_fleet_id


def test_observe_stamps_future_documents_without_moving_past_documents(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    session_id = "authoring-reassignment"

    first = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "checkpoint",
            "prompt": "First authored document",
            "session_id": session_id,
            "summary_points": ["First authored document"],
            "files_touched": ["app/first.py"],
        },
    )
    assert first.status_code == 202, first.text
    first_doc = db.get(V2Document, uuid.UUID(first.json()["document_id"]))
    assert first_doc is not None
    original_fleet_id = first_doc.fleet_session_id

    destination = _create_fleet(client, headers)
    destination_id = uuid.UUID(str(destination["id"]))
    reassigned = client.patch(
        f"{settings.API_V1_STR}/v2/taskforce/session/{session_id}",
        headers=headers,
        json={"fleet_session_id": str(destination_id)},
    )
    assert reassigned.status_code == 200, reassigned.text

    second = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "checkpoint",
            "prompt": "Second authored document",
            "session_id": session_id,
            "summary_points": ["Second authored document"],
            "files_touched": ["app/second.py"],
        },
    )
    assert second.status_code == 202, second.text
    second_doc = db.get(V2Document, uuid.UUID(second.json()["document_id"]))
    assert second_doc is not None
    assert second_doc.fleet_session_id == destination_id

    db.refresh(first_doc)
    assert first_doc.owner_id == user.id
    assert first_doc.fleet_session_id == original_fleet_id

    legacy_global_doc = V2Document(
        owner_id=user.id,
        organization_id=user.organization_id,
        title="Legacy global document",
        fleet_session_id=None,
    )
    db.add(legacy_global_doc)
    db.commit()
    db.refresh(legacy_global_doc)
    updated = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "checkpoint",
            "prompt": "Update a pre-feature document",
            "session_id": session_id,
            "active_document_id": str(legacy_global_doc.id),
            "summary_points": ["Updated the pre-feature document"],
        },
    )
    assert updated.status_code == 202, updated.text
    db.refresh(legacy_global_doc)
    assert legacy_global_doc.fleet_session_id is None


def test_fleet_creates_history_session_and_moves_inactive_agents(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    fleet = _create_fleet(client, headers, "Active sprint")
    fleet_id = uuid.UUID(str(fleet["id"]))
    now = datetime.now(timezone.utc)

    active = _create_archive(
        db,
        user=user,
        session_id="still-running",
        imported_at=now,
        fleet_session_id=fleet_id,
    )
    idle = _create_archive(
        db,
        user=user,
        session_id="went-idle",
        imported_at=now - timedelta(minutes=12),
        fleet_session_id=fleet_id,
    )
    ended = _create_archive(
        db,
        user=user,
        session_id="was-ended",
        imported_at=now - timedelta(minutes=2),
        ended_at=now - timedelta(minutes=2),
        fleet_session_id=fleet_id,
    )
    db.add_all([active, idle, ended])
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/fleet",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    history = next(item for item in body["fleet_sessions"] if item["is_history"])
    active_fleet = next(
        item for item in body["fleet_sessions"] if item["id"] == str(fleet_id)
    )

    assert history["name"] == "History"
    assert {agent["session_id"] for agent in history["agents"]} == {
        "went-idle",
        "was-ended",
    }
    assert [agent["session_id"] for agent in active_fleet["agents"]] == [
        "still-running"
    ]

    db.refresh(idle)
    db.refresh(ended)
    assert idle.fleet_session_id == uuid.UUID(history["id"])
    assert ended.fleet_session_id == uuid.UUID(history["id"])


def test_ended_session_moves_to_history_on_observe(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    session_id = "history-on-end"

    discover = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": "Wrap up the fleet history work", "session_id": session_id},
    )
    assert discover.status_code == 200, discover.text

    observe = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "session_end",
            "prompt": "",
            "session_id": session_id,
        },
    )
    assert observe.status_code == 202, observe.text

    archive = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.actor_id == user.id,
            TaskforceSessionArchive.session_id == session_id,
        )
    ).one()
    history = db.exec(
        select(TaskforceFleetSession)
        .where(TaskforceFleetSession.actor_id == user.id)
        .where(TaskforceFleetSession.is_history.is_(True))
    ).one()
    assert archive.ended_at is not None
    assert archive.fleet_session_id == history.id


def test_discover_resurrects_agent_from_history(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    session_id = "history-resurrect"

    client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": "Initial work", "session_id": session_id},
    )
    client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={"kind": "session_end", "prompt": "", "session_id": session_id},
    )

    archive = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.actor_id == user.id,
            TaskforceSessionArchive.session_id == session_id,
        )
    ).one()
    history_id = archive.fleet_session_id

    revived = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": "Back for more work", "session_id": session_id},
    )
    assert revived.status_code == 200, revived.text

    db.refresh(archive)
    default = db.exec(
        select(TaskforceFleetSession)
        .where(TaskforceFleetSession.actor_id == user.id)
        .where(TaskforceFleetSession.is_history.is_(False))
        .where(TaskforceFleetSession.name == "Session 1")
    ).one()
    assert archive.ended_at is None
    assert archive.fleet_session_id == default.id
    assert archive.fleet_session_id != history_id

    fleet = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/fleet",
        headers=headers,
    )
    assert fleet.status_code == 200, fleet.text
    body = fleet.json()
    history = next(item for item in body["fleet_sessions"] if item["is_history"])
    default_fleet = next(
        item for item in body["fleet_sessions"] if item["id"] == str(default.id)
    )
    assert all(agent["session_id"] != session_id for agent in history["agents"])
    assert [agent["session_id"] for agent in default_fleet["agents"]] == [session_id]


def test_history_session_cannot_be_renamed_or_deleted(
    client: TestClient,
    db: Session,
) -> None:
    _, headers = _signup(client)

    fleet = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/fleet",
        headers=headers,
    )
    assert fleet.status_code == 200, fleet.text
    history = next(
        item for item in fleet.json()["fleet_sessions"] if item["is_history"]
    )

    renamed = client.patch(
        f"{settings.API_V1_STR}/v2/taskforce/fleet/{history['id']}",
        headers=headers,
        json={"name": "Old stuff"},
    )
    assert renamed.status_code == 422, renamed.text

    deleted = client.delete(
        f"{settings.API_V1_STR}/v2/taskforce/fleet/{history['id']}",
        headers=headers,
    )
    assert deleted.status_code == 422, deleted.text
