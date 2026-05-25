from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app.core.agents.seed import (
    DOCUMENT_SLUG_TITLES,
    seed_agents,
    seed_demo_metrics_for_user,
)
from app.core.config import settings
from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    AgentSpecialist,
    AgentSpecialistDocumentLink,
    MetricsEvent,
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
    assert result.links_created == 15

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
