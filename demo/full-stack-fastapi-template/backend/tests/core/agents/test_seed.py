from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, col, func, select

from app.core.agents.seed import (
    DOCUMENT_SLUG_TITLES,
    EMPTY_CELL_ALICE_DOC_TITLE,
    EMPTY_CELL_BOB_PROMPT,
    EMPTY_CELL_SPECIALIST_SLUG,
    link_empty_cell_payments_specialist,
    seed_agents,
    seed_demo_metrics_for_user,
    seed_empty_cell_proof_accounts,
)
from app.core.config import settings
from app.core.taskforce.session import session_start
from app.core.v2_documents import refresh_v2_document_token_counts
from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    AgentSpecialist,
    AgentSpecialistDocumentLink,
    MetricsEvent,
    TaskforceSessionArchive,
    TaskforceSessionEvent,
    TaskforceSessionStartRequest,
    User,
    V2Document,
)
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _signup(client: TestClient) -> tuple[User, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={"email": email, "password": password, "full_name": "Seed Tester"},
    )
    assert 200 <= response.status_code < 300, response.text
    headers = user_authentication_headers(client=client, email=email, password=password)
    token_response = client.get(f"{settings.API_V1_STR}/users/me", headers=headers)
    assert token_response.status_code == 200, token_response.text
    return User.model_validate(token_response.json()), headers


def _db_user(db: Session, user: User) -> User:
    return db.exec(select(User).where(User.id == user.id)).one()


def test_seed_agents_creates_five_specialists_and_links(
    client: TestClient, db: Session
) -> None:
    signed_up, _ = _signup(client)
    user = _db_user(db, signed_up)

    result = seed_agents(db, user)
    db.commit()

    assert result.specialists_created == 5
    assert result.links_created == 16

    specialists = db.exec(
        select(AgentSpecialist)
        .where(AgentSpecialist.is_demo.is_(True))  # type: ignore[union-attr]
        .where(AgentSpecialist.created_from == "seeded")
    ).all()
    assert {specialist.slug for specialist in specialists} == {
        "jensen",
        "mira",
        "orin",
        "vega",
        "nia",
    }

    doc_titles = set(
        db.exec(
            select(V2Document.title)
            .where(V2Document.owner_id == user.id)
            .where(V2Document.is_demo.is_(True))  # type: ignore[union-attr]
        ).all()
    )
    assert set(DOCUMENT_SLUG_TITLES.values()).issubset(doc_titles)

    link_count = db.exec(select(func.count()).select_from(AgentSpecialistDocumentLink))
    assert link_count.one() >= 15


def test_seed_demo_metrics_is_idempotent_and_surfaces_agent_api(
    client: TestClient, db: Session
) -> None:
    signed_up, headers = _signup(client)
    user = _db_user(db, signed_up)

    first = seed_demo_metrics_for_user(db, user)
    db.commit()
    second = seed_demo_metrics_for_user(db, user)
    db.commit()

    assert first.sessions_created >= 40
    assert first.events_created >= 80
    assert second.sessions_created == first.sessions_created
    assert second.events_created == first.events_created

    seeded_consult_count = db.exec(
        select(func.count())
        .select_from(MetricsEvent)
        .where(MetricsEvent.user_id == user.id)
        .where(MetricsEvent.kind == METRICS_EVENT_DOCUMENT_CONSULTED)
        .where(MetricsEvent.is_demo.is_(True))  # type: ignore[union-attr]
        .where(MetricsEvent.payload["seeded"].astext == "true")  # type: ignore[index]
    ).one()
    assert seeded_consult_count >= 23

    list_response = client.get(
        f"{settings.API_V1_STR}/v2/agents?demo=true", headers=headers
    )
    assert list_response.status_code == 200, list_response.text
    items = list_response.json()["items"]
    assert len(items) == 5
    assert {item["slug"] for item in items} == {
        "jensen",
        "mira",
        "orin",
        "vega",
        "nia",
    }
    assert all(item["invocations_count"] > 0 for item in items)

    detail_response = client.get(
        f"{settings.API_V1_STR}/v2/agents/jensen?demo=true", headers=headers
    )
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail["slug"] == "jensen"
    assert len(detail["linked_knowledge"]) >= 3
    assert all("Stripe" in doc["title"] for doc in detail["linked_knowledge"])
    assert detail["recent_invocations"]


def test_seed_demo_metrics_writes_rich_ledger_archives(
    client: TestClient, db: Session
) -> None:
    """Seeded sessions get a full archive + transcript, not the empty state."""

    signed_up, _ = _signup(client)
    user = _db_user(db, signed_up)

    seed_demo_metrics_for_user(db, user)
    db.commit()

    archives = db.exec(
        select(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.actor_id == user.id)
        .where(TaskforceSessionArchive.is_demo.is_(True))  # type: ignore[union-attr]
        .where(
            TaskforceSessionArchive.source_metadata["seeded"].astext == "true"  # type: ignore[index]
        )
    ).all()
    assert len(archives) >= 40

    # Every archive is fully populated — no "Unknown" harness or zeroed counts.
    for archive in archives:
        assert archive.harness_label in {"claude-code", "codex", "cursor"}
        assert archive.model_id
        assert archive.title
        assert archive.display_name
        assert archive.duration_ms > 0
        assert archive.message_count >= 2
        assert archive.command_count >= 1
        assert archive.edit_count >= 1
        assert archive.input_tokens > 0
        assert archive.output_tokens > 0
        assert archive.started_at is not None
        assert archive.ended_at is not None

    # Harness rotation gives all three clients representative traffic.
    assert {a.harness_label for a in archives} == {"claude-code", "codex", "cursor"}

    # Each archived session has a real transcript (prompt + reply drive the
    # "raw transcript available" flag, command/edit render the work).
    sample = archives[0]
    events = db.exec(
        select(TaskforceSessionEvent)
        .where(TaskforceSessionEvent.session_id == sample.session_id)
        .where(TaskforceSessionEvent.is_demo.is_(True))  # type: ignore[union-attr]
    ).all()
    kinds = {event.kind for event in events}
    assert {"prompt", "reply", "command", "edit"}.issubset(kinds)
    assert any(event.kind == "prompt" and event.text for event in events)
    assert any(
        event.kind == "command" and event.cmd and event.output for event in events
    )

    # Re-seeding is idempotent: no duplicate archives or orphaned events.
    seed_demo_metrics_for_user(db, user)
    db.commit()
    archive_count = db.exec(
        select(func.count())
        .select_from(TaskforceSessionArchive)
        .where(TaskforceSessionArchive.actor_id == user.id)
        .where(TaskforceSessionArchive.is_demo.is_(True))  # type: ignore[union-attr]
        .where(
            TaskforceSessionArchive.source_metadata["seeded"].astext == "true"  # type: ignore[index]
        )
    ).one()
    assert archive_count == len(archives)
    seeded_event_count = db.exec(
        select(func.count())
        .select_from(TaskforceSessionEvent)
        .where(TaskforceSessionEvent.actor_id == user.id)
        .where(TaskforceSessionEvent.is_demo.is_(True))  # type: ignore[union-attr]
        .where(col(TaskforceSessionEvent.source_event_id).like("tf198seed-%"))
    ).one()
    # Each session emits at least 7 events (prompt + 2 replies + note + 2
    # commands + 1-2 edits); the reseed must not have doubled them.
    assert seeded_event_count >= len(archives) * 7


def test_seeded_jensen_routes_demo_session_start(
    client: TestClient, db: Session
) -> None:
    signed_up, headers = _signup(client)
    user = _db_user(db, signed_up)
    seed_demo_metrics_for_user(db, user)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/session/start",
        headers=headers,
        json={
            "demo": True,
            "prompt": (
                "Stripe is double-charging some users on plan upgrade. "
                "It looks like webhook retries are fulfilled twice."
            ),
            "files": ["app/api/routes/billing.py", "app/core/stripe_billing.py"],
            "min_score": 0.0,
        },
    )

    assert response.status_code == 201, response.text
    matched = response.json()["matched_specialist"]
    assert matched is not None
    assert matched["slug"] == "jensen"
    assert matched["band"] in {"high", "medium"}
    assert matched["linked_documents"]


def test_empty_cell_seed_routes_bob_to_alice_codex_document(db: Session) -> None:
    seed = seed_empty_cell_proof_accounts(db)
    document = V2Document(
        owner_id=seed.alice.id,
        organization_id=seed.organization.id,
        visibility="organization",
        produced_by_client="codex",
        title=EMPTY_CELL_ALICE_DOC_TITLE,
        description=(
            "Stripe refund webhook retries must persist event ids before "
            "issuing refund side effects."
        ),
        human_summary="",
        ai_generated_summary=(
            "Durable Stripe event-id idempotency prevents duplicate refund "
            "webhook side effects."
        ),
        collaborators=[],
        main_body=[
            {
                "segments": [
                    {
                        "text": (
                            "Store each Stripe event id before issuing a refund "
                            "and short-circuit duplicate webhook delivery."
                        )
                    }
                ]
            }
        ],
        details_file_name="taskforce.details.md",
        details_markdown_sections=[
            {
                "anchor_id": "stripe-event-idempotency",
                "markdown": (
                    "Refund webhooks can be retried by Stripe. Use a durable "
                    "processed-events table keyed by event id before running "
                    "the refund side effect. app/api/routes/billing.py"
                ),
            }
        ],
        is_demo=False,
    )
    refresh_v2_document_token_counts(document)
    db.add(document)
    db.flush()
    link = link_empty_cell_payments_specialist(
        db,
        specialist=seed.specialist,
        document=document,
    )
    db.flush()

    response = session_start(
        db,
        actor=seed.bob,
        request=TaskforceSessionStartRequest(
            prompt=EMPTY_CELL_BOB_PROMPT,
            client="claude-code",
            files=["app/api/routes/billing.py"],
            min_score=0.0,
            demo=False,
        ),
    )

    assert seed.organization.name == "Acme"
    assert seed.alice.organization_id == seed.bob.organization_id
    assert seed.specialist.slug == EMPTY_CELL_SPECIALIST_SLUG
    assert seed.specialist.visibility == "organization"
    assert seed.specialist.is_demo is False
    assert link.anchor_id == "stripe-event-idempotency"
    assert response.matched_specialist is not None
    assert response.matched_specialist.slug == EMPTY_CELL_SPECIALIST_SLUG
    assert document.id in {match.document_id for match in response.matches}

    event = db.exec(
        select(MetricsEvent)
        .where(MetricsEvent.user_id == seed.bob.id)
        .where(MetricsEvent.kind == METRICS_EVENT_DOCUMENT_CONSULTED)
        .where(MetricsEvent.document_id == document.id)
    ).first()
    assert event is not None
    assert event.payload["consumed_by_client"] == "claude-code"
    assert event.payload["specialist_slug"] == EMPTY_CELL_SPECIALIST_SLUG
    assert event.input_tokens is not None
    assert event.input_tokens > 0
