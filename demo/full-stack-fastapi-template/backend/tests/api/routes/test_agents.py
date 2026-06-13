from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select

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


def _signup(client: TestClient) -> tuple[str, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={"email": email, "password": password, "full_name": "Agents Tester"},
    )
    assert 200 <= response.status_code < 300, response.text
    headers = user_authentication_headers(client=client, email=email, password=password)
    return email, headers


def _user_by_email(db: Session, email: str) -> User:
    return db.exec(select(User).where(User.email == email)).one()


def _agent(db: Session, user: User, **kwargs: Any) -> AgentSpecialist:
    specialist = AgentSpecialist(
        owner_id=kwargs.pop("owner_id", user.id),
        organization_id=kwargs.pop("organization_id", user.organization_id),
        slug=kwargs.pop("slug", f"agent-{random_lower_string()}"),
        name=kwargs.pop("name", "Jensen"),
        role=kwargs.pop("role", "Billing Reliability Specialist"),
        short_description=kwargs.pop(
            "short_description",
            "Stripe webhooks, subscriptions, and double-charge prevention.",
        ),
        description=kwargs.pop("description", "Helps debug Stripe billing."),
        status=kwargs.pop("status", "active"),
        visibility=kwargs.pop("visibility", "private"),
        domain_tags=kwargs.pop("domain_tags", ["Stripe", "Billing"]),
        routing_triggers=kwargs.pop("routing_triggers", ["stripe", "webhook"]),
        negative_triggers=kwargs.pop("negative_triggers", ["pricing page copy"]),
        instructions=kwargs.pop("instructions", ["Check webhook idempotency."]),
        is_demo=kwargs.pop("is_demo", False),
        **kwargs,
    )
    db.add(specialist)
    db.commit()
    db.refresh(specialist)
    return specialist


def _document(db: Session, user: User, *, title: str = "Linked doc") -> V2Document:
    document = V2Document(
        owner_id=user.id,
        organization_id=user.organization_id,
        visibility="private",
        title=title,
        description="Decision record for route-boundary WAL dedupe.",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def test_list_agents_returns_empty_until_seeded(client: TestClient) -> None:
    _, headers = _signup(client)

    response = client.get(f"{settings.API_V1_STR}/v2/agents", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}


def test_list_agents_returns_accessible_summaries_with_stats(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    specialist = _agent(db, user, slug=f"jensen-{random_lower_string()}")
    document = _document(db, user)
    db.add(
        AgentSpecialistDocumentLink(
            specialist_id=specialist.id,
            document_id=document.id,
            anchor_id="decision-wal-table",
            reason="Pinned decision record",
            is_pinned=True,
        )
    )
    db.add(
        MetricsEvent(
            occurred_at=datetime(2026, 5, 24, 12, tzinfo=timezone.utc),
            user_id=user.id,
            document_id=document.id,
            kind=METRICS_EVENT_DOCUMENT_CONSULTED,
            input_tokens=42000,
            usd_amount=Decimal("0.630000"),
            payload={
                "specialist_slug": specialist.slug,
                "session_id": "session-1",
                "prompt": "Stripe is double-charging users.",
            },
        )
    )
    db.commit()

    response = client.get(f"{settings.API_V1_STR}/v2/agents", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"][0]["slug"] == specialist.slug
    assert body["items"][0]["linked_docs_count"] == 1
    assert body["items"][0]["invocations_count"] == 1
    assert body["items"][0]["tokens_saved"] == 42000
    assert body["items"][0]["last_invoked_at"] == "2026-05-24T12:00:00Z"


def test_get_agent_returns_detail_with_linked_knowledge_and_invocations(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    specialist = _agent(db, user, slug=f"jensen-{random_lower_string()}")
    document = _document(db, user, title="Stripe webhook idempotency strategy")
    db.add(
        AgentSpecialistDocumentLink(
            specialist_id=specialist.id,
            document_id=document.id,
            anchor_id="decision-wal-table",
            reason="Pinned decision record",
            is_pinned=True,
        )
    )
    db.add(
        MetricsEvent(
            occurred_at=datetime(2026, 5, 24, 12, tzinfo=timezone.utc),
            user_id=user.id,
            document_id=document.id,
            kind=METRICS_EVENT_DOCUMENT_CONSULTED,
            input_tokens=28432,
            usd_amount=Decimal("0.420000"),
            payload={
                "specialist_slug": specialist.slug,
                "session_id": "session-2",
                "prompt": "Fix Stripe webhook retry ordering.",
                "summary": "Fixed webhook replay ordering regression.",
                "repo": "taskforce-claude",
                "branch": "demo/stripe-double-charge",
                "documents_consulted_count": 2,
            },
        )
    )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/v2/agents/{specialist.slug}",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["slug"] == specialist.slug
    assert body["status"] == "active"
    assert body["linked_knowledge"][0]["href"] == (
        f"/v2/library/{document.id}#decision-wal-table"
    )
    assert body["recent_invocations"][0]["prompt"] == (
        "Fix Stripe webhook retry ordering."
    )
    assert body["recent_invocations"][0]["session_id"] == "session-2"
    assert body["stats"]["tokens_saved"] == 28432
    assert body["stats"]["usd_saved"] == "0.420000"


def test_get_agent_404_for_unknown_slug(client: TestClient) -> None:
    _, headers = _signup(client)

    response = client.get(
        f"{settings.API_V1_STR}/v2/agents/{uuid.uuid4()}",
        headers=headers,
    )

    assert response.status_code == 404


def test_get_agent_403_for_acl_denied(client: TestClient, db: Session) -> None:
    email, _ = _signup(client)
    owner = _user_by_email(db, email)
    specialist = _agent(db, owner, slug=f"private-{random_lower_string()}")
    _, outsider_headers = _signup(client)

    response = client.get(
        f"{settings.API_V1_STR}/v2/agents/{specialist.slug}",
        headers=outsider_headers,
    )

    assert response.status_code == 403


def test_create_agent_persists_and_is_listed(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)

    response = client.post(
        f"{settings.API_V1_STR}/v2/agents",
        headers=headers,
        json={
            "name": "Billing Specialist",
            "role": "Stripe billing & webhooks",
            "short_description": "Owns the checkout surface.",
            "domain_tags": ["billing", "  ", "payments"],
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["slug"] == "billing-specialist"
    assert body["status"] == "active"
    assert body["name"] == "Billing Specialist"
    assert body["role"] == "Stripe billing & webhooks"
    assert body["domain_tags"] == ["billing", "payments"]
    assert body["created_from"] == "manual"

    stored = db.exec(
        select(AgentSpecialist).where(AgentSpecialist.slug == "billing-specialist")
    ).one()
    assert stored.owner_id == user.id
    assert stored.status == "active"

    listed = client.get(f"{settings.API_V1_STR}/v2/agents", headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(item["slug"] == "billing-specialist" for item in listed.json()["items"])


def test_create_agent_generates_unique_slug(client: TestClient) -> None:
    _, headers = _signup(client)
    name = f"Billing Specialist {random_lower_string()}"
    payload = {"name": name, "role": "Stripe"}
    expected_slug = "-".join(name.lower().split())

    first = client.post(
        f"{settings.API_V1_STR}/v2/agents", headers=headers, json=payload
    )
    second = client.post(
        f"{settings.API_V1_STR}/v2/agents", headers=headers, json=payload
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["slug"] == expected_slug
    assert second.json()["slug"] == f"{expected_slug}-2"


def test_create_agent_requires_name_and_role(client: TestClient) -> None:
    _, headers = _signup(client)

    response = client.post(
        f"{settings.API_V1_STR}/v2/agents",
        headers=headers,
        json={"name": "", "role": ""},
    )

    assert response.status_code == 422


def test_update_agent_changes_fields_and_keeps_slug(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    specialist = _agent(db, user, slug=f"jensen-{random_lower_string()}")
    original_slug = specialist.slug

    response = client.patch(
        f"{settings.API_V1_STR}/v2/agents/{original_slug}",
        headers=headers,
        json={
            "name": "Renamed Specialist",
            "role": "Payments reliability",
            "short_description": "Now owns refunds too.",
            "domain_tags": ["refunds", "  ", "payments"],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["slug"] == original_slug
    assert body["name"] == "Renamed Specialist"
    assert body["role"] == "Payments reliability"
    assert body["domain_tags"] == ["refunds", "payments"]

    stored = db.exec(
        select(AgentSpecialist).where(AgentSpecialist.slug == original_slug)
    ).one()
    db.refresh(stored)
    assert stored.name == "Renamed Specialist"
    assert stored.short_description == "Now owns refunds too."


def test_update_agent_partial_leaves_other_fields(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    specialist = _agent(db, user, slug=f"jensen-{random_lower_string()}")

    response = client.patch(
        f"{settings.API_V1_STR}/v2/agents/{specialist.slug}",
        headers=headers,
        json={"role": "Only the role changed"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "Only the role changed"
    assert body["name"] == "Jensen"
    assert body["domain_tags"] == ["Stripe", "Billing"]


def test_update_agent_status_lifecycle_and_list_visibility(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    specialist = _agent(db, user, slug=f"jensen-{random_lower_string()}")

    for status in ("draft", "archived", "active"):
        response = client.patch(
            f"{settings.API_V1_STR}/v2/agents/{specialist.slug}",
            headers=headers,
            json={"status": status},
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == status

        listed = client.get(f"{settings.API_V1_STR}/v2/agents", headers=headers)
        assert listed.status_code == 200, listed.text
        listed_agent = next(
            item
            for item in listed.json()["items"]
            if item["slug"] == specialist.slug
        )
        assert listed_agent["status"] == status

        detail = client.get(
            f"{settings.API_V1_STR}/v2/agents/{specialist.slug}",
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["status"] == status


def test_update_agent_rejects_invalid_status(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    specialist = _agent(db, user, slug=f"jensen-{random_lower_string()}")

    response = client.patch(
        f"{settings.API_V1_STR}/v2/agents/{specialist.slug}",
        headers=headers,
        json={"status": "paused"},
    )

    assert response.status_code == 422


def test_update_agent_rejects_blank_name(client: TestClient, db: Session) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    specialist = _agent(db, user, slug=f"jensen-{random_lower_string()}")

    response = client.patch(
        f"{settings.API_V1_STR}/v2/agents/{specialist.slug}",
        headers=headers,
        json={"name": "   "},
    )

    assert response.status_code == 422


def test_update_agent_403_for_non_owner(client: TestClient, db: Session) -> None:
    email, _ = _signup(client)
    owner = _user_by_email(db, email)
    specialist = _agent(db, owner, slug=f"private-{random_lower_string()}")
    _, outsider_headers = _signup(client)

    response = client.patch(
        f"{settings.API_V1_STR}/v2/agents/{specialist.slug}",
        headers=outsider_headers,
        json={"name": "Hijacked"},
    )

    assert response.status_code == 403


def test_update_agent_status_403_for_non_owner(
    client: TestClient, db: Session
) -> None:
    email, _ = _signup(client)
    owner = _user_by_email(db, email)
    specialist = _agent(db, owner, slug=f"private-{random_lower_string()}")
    _, outsider_headers = _signup(client)

    response = client.patch(
        f"{settings.API_V1_STR}/v2/agents/{specialist.slug}",
        headers=outsider_headers,
        json={"status": "archived"},
    )

    assert response.status_code == 403


def test_delete_agent_removes_profile(client: TestClient, db: Session) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    specialist = _agent(db, user, slug=f"jensen-{random_lower_string()}")
    document = _document(db, user)
    db.add(
        AgentSpecialistDocumentLink(
            specialist_id=specialist.id,
            document_id=document.id,
            reason="Pinned decision record",
            is_pinned=True,
        )
    )
    db.commit()
    slug = specialist.slug

    response = client.delete(
        f"{settings.API_V1_STR}/v2/agents/{slug}",
        headers=headers,
    )

    assert response.status_code == 204, response.text
    assert (
        db.exec(select(AgentSpecialist).where(AgentSpecialist.slug == slug)).first()
        is None
    )
    # Linked rows cascade away with the specialist.
    assert (
        db.exec(
            select(AgentSpecialistDocumentLink).where(
                AgentSpecialistDocumentLink.specialist_id == specialist.id
            )
        ).first()
        is None
    )

    follow_up = client.get(
        f"{settings.API_V1_STR}/v2/agents/{slug}", headers=headers
    )
    assert follow_up.status_code == 404


def test_delete_agent_403_for_non_owner(client: TestClient, db: Session) -> None:
    email, _ = _signup(client)
    owner = _user_by_email(db, email)
    specialist = _agent(db, owner, slug=f"private-{random_lower_string()}")
    _, outsider_headers = _signup(client)

    response = client.delete(
        f"{settings.API_V1_STR}/v2/agents/{specialist.slug}",
        headers=outsider_headers,
    )

    assert response.status_code == 403
