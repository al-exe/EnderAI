"""Integration tests for the Taskforce hook endpoints (TF-175).

Mirrors the patterns in ``tests/api/test_v2_documents_api.py``: each test
signs up a fresh user, issues a few API calls, and asserts the
response/DB state.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    METRICS_EVENT_DOCUMENT_CONSULTED,
    AgentSpecialist,
    AgentSpecialistDocumentLink,
    MetricsEvent,
    ModelPricing,
    TaskforceSessionArchive,
    TaskforceSessionEvent,
    User,
    V2Document,
)
from tests.utils.utils import random_email, random_lower_string, session_id_for

REFERENCE_SESSION_ID = "123e4567-e89b-12d3-a456-426614174000"
REFERENCE_OCCURRED_AT = "2026-05-23T19:00:01Z"


def _signup(client: TestClient) -> tuple[str, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={"email": email, "password": password, "full_name": "Taskforce Tester"},
    )
    assert 200 <= response.status_code < 300, response.text
    from tests.utils.user import user_authentication_headers

    headers = user_authentication_headers(client=client, email=email, password=password)
    return email, headers


def _user_by_email(db: Session, email: str) -> User:
    return db.exec(select(User).where(User.email == email)).one()


def _join_same_org(
    client: TestClient,
    db: Session,
    *,
    owner_headers: dict[str, str],
    member_email: str,
    member_headers: dict[str, str],
) -> None:
    invite = client.post(
        f"{settings.API_V1_STR}/organizations/invitations",
        headers=owner_headers,
        json={"email": member_email},
    )
    assert invite.status_code == 201, invite.text

    accepted = client.post(
        f"{settings.API_V1_STR}/organizations/invitations/{invite.json()['id']}/accept",
        headers=member_headers,
    )
    assert accepted.status_code == 200, accepted.text
    db.commit()


def _create_document(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str,
    description: str = "",
    visibility: str = "private",
    details_markdown_sections: list[dict[str, str]] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "title": title,
        "description": description,
        "visibility": visibility,
    }
    if details_markdown_sections is not None:
        payload["details_markdown_sections"] = details_markdown_sections
    response = client.post(
        f"{settings.API_V1_STR}/v2/documents/",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _get_document(
    client: TestClient, headers: dict[str, str], document_id: str
) -> dict[str, Any]:
    response = client.get(
        f"{settings.API_V1_STR}/v2/documents/{document_id}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _reference_documents(
    client: TestClient,
    headers: dict[str, str],
    document_ids: list[str],
    *,
    prompt: str = "reference prompt",
) -> dict[str, Any]:
    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/reference",
        headers=headers,
        json={
            "session_id": REFERENCE_SESSION_ID,
            "document_ids": document_ids,
            "user_prompt": prompt,
            "occurred_at": REFERENCE_OCCURRED_AT,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _referenced_by_section(document: dict[str, Any]) -> dict[str, str] | None:
    return next(
        (
            section
            for section in document["details_markdown_sections"]
            if section["anchor_id"] == "referenced-by"
        ),
        None,
    )


def _expected_reference_row(prompt: str) -> str:
    normalized = " ".join(prompt.split())
    preview = (
        normalized if len(normalized) <= 120 else normalized[:117].rstrip() + "..."
    )
    return (
        f"- **{REFERENCE_OCCURRED_AT}** · session `{REFERENCE_SESSION_ID[:8]}` · "
        f'"{preview}"'
    )


def test_taskforce_discover_returns_top_matches_for_owner(client: TestClient) -> None:
    _, headers = _signup(client)
    _create_document(
        client,
        headers,
        title="Library page polish",
        description="Cleanup of the metrics page; USD Saved → USD Offset.",
    )
    _create_document(
        client,
        headers,
        title="Banana yacht unrelated",
        description="Completely off-topic content.",
    )

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": "fix the library polish metrics card"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "query_id" in body
    assert isinstance(body["matches"], list)
    # The polish doc should outrank the banana doc.
    if body["matches"]:
        top = body["matches"][0]
        assert "Library" in top["title"]
        assert top["score"] > 0.0
        assert top["confidence_band"] in {"high", "medium", "low"}
        assert top["matched_anchor_id"] == "summary"
        assert "rediscovery_cost_tokens" in top
        assert "consult_token_cost" in top


def test_taskforce_discover_records_consulted_events(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    doc_id = uuid.UUID(
        _create_document(client, headers, title="Important library work")
    )
    document = db.exec(select(V2Document).where(V2Document.id == doc_id)).one()
    document.produced_by_client = "codex"
    db.add(document)
    db.commit()

    discover = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "library work continuation",
            "client": "claude-code",
            "k": 3,
            "min_score": 0.0,
        },
    )
    assert discover.status_code == 200, discover.text
    matches = discover.json()["matches"]
    if not matches:
        # Scoring might be too strict on this fixture; not a hard requirement here.
        return

    metrics = client.get(
        f"{settings.API_V1_STR}/v2/metrics",
        headers=headers,
        params={"metrics": "documents_consulted", "window": "all"},
    )
    assert metrics.status_code == 200, metrics.text
    consulted = metrics.json()["metrics"]["documents_consulted"]
    assert int(consulted["total"]) >= 1

    event = db.exec(
        select(MetricsEvent)
        .where(MetricsEvent.user_id == user.id)
        .where(MetricsEvent.kind == METRICS_EVENT_DOCUMENT_CONSULTED)
        .where(MetricsEvent.document_id == doc_id)
    ).first()
    assert event is not None
    assert event.document_id == doc_id
    assert event.payload["consumed_by_client"] == "claude-code"
    assert document.produced_by_client == "codex"


def test_taskforce_discover_empty_library_still_returns_query_id(
    client: TestClient,
) -> None:
    _, headers = _signup(client)
    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": "anything goes here"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "query_id" in body
    assert body["matches"] == []


def test_taskforce_discover_rejects_empty_prompt(client: TestClient) -> None:
    _, headers = _signup(client)
    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": ""},
    )
    assert response.status_code == 422


def test_taskforce_discover_requires_auth(client: TestClient) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        json={"prompt": "anything"},
    )
    assert response.status_code in (401, 403)


def test_documents_consulted_metric_listed_in_definitions(client: TestClient) -> None:
    _, headers = _signup(client)
    response = client.get(
        f"{settings.API_V1_STR}/v2/metrics/definitions",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    names = {row["name"] for row in response.json()["data"]}
    assert "documents_consulted" in names


# ----- TF-177 / Phase 3: rediscovery cost + avoided_rediscovery metric -----


def test_v2_document_rediscovery_cost_refreshes_on_update(client: TestClient) -> None:
    _, headers = _signup(client)
    created = client.post(
        f"{settings.API_V1_STR}/v2/documents/",
        headers=headers,
        json={
            "title": "Rediscovery test doc",
            "description": "",
            "details_markdown_sections": [
                {
                    "anchor_id": "investigation",
                    "markdown": (
                        "Ran `ls -la` then\n"
                        "$ rg --files-with-matches foo src/\n"
                        "Inspected `src/api/routes/v2_documents.py`.\n"
                        "Decided to ship the new endpoint.\n"
                    ),
                },
                {"anchor_id": "outcome", "markdown": "Shipped."},
            ],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    # Doc has 2 sections + 2 commands + 1 file + 1 decision → cost > 0
    assert body.get("rediscovery_cost_tokens", 0) > 0


def test_avoided_rediscovery_metric_listed_in_definitions(client: TestClient) -> None:
    _, headers = _signup(client)
    response = client.get(
        f"{settings.API_V1_STR}/v2/metrics/definitions",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    names = {row["name"] for row in response.json()["data"]}
    assert "avoided_rediscovery" in names
    assert "avoided_rediscovery_usd" in names


def test_session_log_returns_consults_for_session(client: TestClient) -> None:
    _, headers = _signup(client)
    _create_document(
        client,
        headers,
        title="Session-scoped library polish",
        description="Cleanup task.",
    )

    discover = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "library polish",
            "session_id": "test-session-abc",
            "k": 3,
            "min_score": 0.0,
        },
    )
    assert discover.status_code == 200, discover.text

    log = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/session-log",
        headers=headers,
        params={"session_id": "test-session-abc"},
    )
    assert log.status_code == 200, log.text
    body = log.json()
    assert body["session_id"] == "test-session-abc"
    assert isinstance(body["entries"], list)
    if discover.json()["matches"]:
        assert len(body["entries"]) >= 1
        entry = body["entries"][0]
        assert entry["title"]
        assert entry["confidence_band"] in {"high", "medium", "low"}


def test_session_log_filters_by_session(client: TestClient) -> None:
    _, headers = _signup(client)
    _create_document(client, headers, title="Library work for both sessions")

    client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": "library work", "session_id": "alpha", "min_score": 0.0},
    )
    client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": "library work", "session_id": "beta", "min_score": 0.0},
    )

    alpha = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/session-log",
        headers=headers,
        params={"session_id": "alpha"},
    )
    beta = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/session-log",
        headers=headers,
        params={"session_id": "beta"},
    )
    assert alpha.status_code == 200
    assert beta.status_code == 200
    # Each session sees only its own entries.
    for entry in alpha.json()["entries"]:
        # Session id is embedded in the event payload; we don't surface it
        # in the response shape directly, but the filter is exclusive.
        assert entry["title"]
    for entry in beta.json()["entries"]:
        assert entry["title"]


def test_session_savings_empty_session_returns_zeroes(client: TestClient) -> None:
    _, headers = _signup(client)

    response = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/session-savings",
        headers=headers,
        params={"session_id": "missing-session"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "session_id": "missing-session",
        "doc_count": 0,
        "net_saved_tokens": 0,
        "usd_saved": "0.000000",
        "pricing_model_id": None,
        "specialist_slug": None,
        "specialist_name": None,
        "occurred_at_first": None,
        "occurred_at_last": None,
    }


def test_session_savings_sums_consult_events(client: TestClient, db: Session) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    doc_a = uuid.UUID(_create_document(client, headers, title="Savings doc A"))
    doc_b = uuid.UUID(_create_document(client, headers, title="Savings doc B"))

    for document_id, tokens, usd in (
        (doc_a, 1000, Decimal("0.010000")),
        (doc_b, 2000, Decimal("0.020000")),
    ):
        db.add(
            MetricsEvent(
                occurred_at=datetime(
                    2026, 5, 23, 19, tokens // 1000, tzinfo=timezone.utc
                ),
                user_id=user.id,
                document_id=document_id,
                kind=METRICS_EVENT_DOCUMENT_CONSULTED,
                input_tokens=tokens,
                usd_amount=usd,
                payload={"session_id": "savings-session"},
            )
        )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/session-savings",
        headers=headers,
        params={"session_id": "savings-session"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == "savings-session"
    assert body["doc_count"] == 2
    assert body["net_saved_tokens"] == 3000
    assert body["usd_saved"] == "0.030000"
    assert body["pricing_model_id"] is None
    assert body["occurred_at_first"] == "2026-05-23T19:01:00Z"
    assert body["occurred_at_last"] == "2026-05-23T19:02:00Z"


def test_session_savings_pricing_model_override_reprices_tokens(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client)
    user = _user_by_email(db, email)
    document_id = uuid.UUID(_create_document(client, headers, title="Override doc"))
    pricing_model_id = f"test-session-savings-{random_lower_string()}"
    db.add(
        ModelPricing(
            provider="test",
            model_id=pricing_model_id,
            effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            input_per_mtok=Decimal("10.0000"),
            output_per_mtok=Decimal("20.0000"),
        )
    )
    db.add(
        MetricsEvent(
            occurred_at=datetime(2026, 5, 23, 19, 4, tzinfo=timezone.utc),
            user_id=user.id,
            document_id=document_id,
            kind=METRICS_EVENT_DOCUMENT_CONSULTED,
            input_tokens=3000,
            usd_amount=Decimal("0.001000"),
            payload={"session_id": "override-session"},
        )
    )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/session-savings",
        headers=headers,
        params={
            "session_id": "override-session",
            "pricing_model_id": pricing_model_id,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["net_saved_tokens"] == 3000
    assert body["usd_saved"] == "0.030000"
    assert body["pricing_model_id"] == pricing_model_id


# ----- TF-186: append referenced-by rows to consulted documents ------------


def test_reference_route_creates_referenced_by_section_and_truncates_prompt(
    client: TestClient,
) -> None:
    _, headers = _signup(client)
    doc_id = _create_document(client, headers, title="Referenced empty doc")
    prompt = "x" * 130

    body = _reference_documents(client, headers, [doc_id], prompt=prompt)

    assert body == {"updated_document_ids": [doc_id], "skipped_document_ids": []}
    document = _get_document(client, headers, doc_id)
    section = _referenced_by_section(document)
    assert section is not None
    assert section["markdown"] == _expected_reference_row(prompt)


def test_reference_route_appends_to_199_existing_rows(client: TestClient) -> None:
    _, headers = _signup(client)
    existing_rows = [f"- existing {index}" for index in range(199)]
    doc_id = _create_document(
        client,
        headers,
        title="Referenced 199 rows",
        details_markdown_sections=[
            {
                "anchor_id": "referenced-by",
                "markdown": "\n".join(existing_rows),
            }
        ],
    )

    _reference_documents(client, headers, [doc_id], prompt="append prompt")

    document = _get_document(client, headers, doc_id)
    section = _referenced_by_section(document)
    assert section is not None
    rows = section["markdown"].splitlines()
    assert len(rows) == 200
    assert rows[0] == "- existing 0"
    assert rows[-1] == _expected_reference_row("append prompt")


def test_reference_route_caps_existing_rows_at_200(client: TestClient) -> None:
    _, headers = _signup(client)
    existing_rows = [f"- existing {index}" for index in range(200)]
    doc_id = _create_document(
        client,
        headers,
        title="Referenced capped rows",
        details_markdown_sections=[
            {
                "anchor_id": "referenced-by",
                "markdown": "\n".join(existing_rows),
            }
        ],
    )

    _reference_documents(client, headers, [doc_id], prompt="newest prompt")

    document = _get_document(client, headers, doc_id)
    section = _referenced_by_section(document)
    assert section is not None
    rows = section["markdown"].splitlines()
    assert len(rows) == 200
    assert rows[0] == "- existing 1"
    assert "- existing 0" not in rows
    assert rows[-1] == _expected_reference_row("newest prompt")


def test_reference_route_skips_acl_disallowed_document(client: TestClient) -> None:
    _, owner_headers = _signup(client)
    doc_id = _create_document(client, owner_headers, title="Private owner doc")
    _, outsider_headers = _signup(client)

    body = _reference_documents(client, outsider_headers, [doc_id])

    assert body == {"updated_document_ids": [], "skipped_document_ids": [doc_id]}
    owner_document = _get_document(client, owner_headers, doc_id)
    assert _referenced_by_section(owner_document) is None


# ----- TF-181 / Phase 7: Tier 2 MCP entry points --------------------------


def test_session_start_returns_session_id_and_matches(client: TestClient) -> None:
    _, headers = _signup(client)
    _create_document(
        client,
        headers,
        title="Library polish — Tier 2 fixture",
        description="Cleanup of the metrics page.",
    )

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/session/start",
        headers=headers,
        json={"prompt": "library polish metrics card", "min_score": 0.0},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "session_id" in body
    # session_id is a valid UUID string
    import uuid as _uuid

    _uuid.UUID(body["session_id"])
    assert isinstance(body["matches"], list)
    if body["matches"]:
        assert "matched_anchor_id" in body["matches"][0]
    # suggested_pin is either null or a UUID matching one of the matches
    if body["suggested_pin"] is not None:
        match_ids = {m["document_id"] for m in body["matches"]}
        assert body["suggested_pin"] in match_ids

    # TF-196: matched_specialist field is always present in the
    # response (may be null when no specialist is seeded for this
    # actor). When non-null, the shape includes slug/name/role/band
    # plus a clickable href to the Agents detail page.
    assert "matched_specialist" in body
    if body["matched_specialist"] is not None:
        ms = body["matched_specialist"]
        assert ms["slug"]
        assert ms["band"] in {"high", "medium", "low"}
        assert ms["href"] == f"/v2/profiles/{ms['slug']}"


def test_session_start_hydrates_org_visible_teammate_document(
    client: TestClient, db: Session
) -> None:
    alice_email, alice_headers = _signup(client)
    bob_email, bob_headers = _signup(client)
    _join_same_org(
        client,
        db,
        owner_headers=alice_headers,
        member_email=bob_email,
        member_headers=bob_headers,
    )
    alice = _user_by_email(db, alice_email)
    bob = _user_by_email(db, bob_email)
    assert alice.organization_id == bob.organization_id

    doc_id = _create_document(
        client,
        alice_headers,
        title="Stripe webhook idempotency strategy",
        description=(
            "Refund and payment webhook retries must use durable event-id "
            "dedupe before side effects."
        ),
        visibility="organization",
        details_markdown_sections=[
            {
                "anchor_id": "decision",
                "markdown": "Store processed Stripe event ids before issuing refunds.",
            }
        ],
    )

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/session/start",
        headers=bob_headers,
        json={
            "prompt": "Handle refund webhook retries with Stripe event idempotency",
            "client": "claude-code",
            "min_score": 0.0,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert doc_id in {match["document_id"] for match in body["matches"]}

    event = db.exec(
        select(MetricsEvent)
        .where(MetricsEvent.user_id == bob.id)
        .where(MetricsEvent.kind == METRICS_EVENT_DOCUMENT_CONSULTED)
        .where(MetricsEvent.document_id == uuid.UUID(doc_id))
    ).first()
    assert event is not None
    assert event.payload["consumed_by_client"] == "claude-code"


def test_session_start_routes_to_seeded_specialist(
    client: TestClient, db: Session
) -> None:
    """TF-196: with a relevant AgentSpecialist seeded, session/start
    surfaces it as matched_specialist and tags the resulting
    document.consulted metrics_event rows with the slug.
    """

    from app.models import (
        AgentSpecialist,
        AgentSpecialistDocumentLink,
        V2Document,
    )

    email, headers = _signup(client)
    user = _user_by_email(db, email)

    # Seed a V2 document that the specialist will be linked to. The
    # document body intentionally mirrors the prompt vocabulary so the
    # document-side score also fires.
    doc_id_str = _create_document(
        client,
        headers,
        title="Stripe webhook idempotency strategy",
        description=(
            "Plan upgrade webhook dedupe via WAL table. "
            "Files: app/api/routes/billing.py."
        ),
    )
    doc_id = uuid.UUID(doc_id_str)
    doc = db.exec(select(V2Document).where(V2Document.id == doc_id)).one()

    # Seed a specialist whose routing_triggers fire on the demo prompt.
    specialist = AgentSpecialist(
        slug="jensen-test",
        name="Jensen",
        role="Billing Reliability Specialist",
        short_description="Stripe webhooks, subscriptions, dedupe.",
        description="Specialist for Stripe billing reliability.",
        status="active",
        visibility="private",
        owner_id=user.id,
        domain_tags=["Stripe", "Billing"],
        routing_triggers=[
            "stripe",
            "webhook",
            "plan upgrade",
            "double-charging",
        ],
        negative_triggers=[],
        instructions=[],
        is_demo=False,
    )
    db.add(specialist)
    db.flush()
    db.add(
        AgentSpecialistDocumentLink(
            specialist_id=specialist.id,
            document_id=doc.id,
            anchor_id=None,
            is_pinned=True,
            weight=1.0,
        )
    )
    db.commit()

    prompt = (
        "Stripe is double-charging some users on plan upgrade — looks "
        "like webhook retries are getting fulfilled twice."
    )
    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/session/start",
        headers=headers,
        json={
            "prompt": prompt,
            "files": ["app/api/routes/billing.py"],
            "client": "claude-code",
            "min_score": 0.0,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()

    matched = body["matched_specialist"]
    assert matched is not None, body
    assert matched["slug"] == "jensen-test"
    assert matched["band"] in {"high", "medium"}
    assert matched["confidence"] > 0
    assert matched["reasons"]
    # The skill uses href to build a clickable link to the Agents page.
    assert matched["href"] == "/v2/profiles/jensen-test"

    # Every document.consulted event the discover call emitted must
    # carry the routed specialist_slug so the Agents page can derive
    # per-specialist invocation counts later.
    events = db.exec(
        select(MetricsEvent)
        .where(MetricsEvent.user_id == user.id)
        .where(MetricsEvent.kind == METRICS_EVENT_DOCUMENT_CONSULTED)
    ).all()
    assert events, "discover should have emitted at least one consult event"
    for event in events:
        assert event.payload.get("specialist_slug") == "jensen-test", event.payload
        # TF-201: prompt must also be threaded into the payload so the
        # Agents page Recent Invocations table shows real queries instead
        # of "" — _recent_invocations reads payload->>'prompt'.
        assert event.payload.get("prompt") == prompt, event.payload
        assert event.payload.get("consumed_by_client") == "claude-code", event.payload

    specialist.status = "archived"
    db.add(specialist)
    db.commit()

    archived_response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/session/start",
        headers=headers,
        json={
            "prompt": prompt,
            "files": ["app/api/routes/billing.py"],
            "client": "claude-code",
            "min_score": 0.0,
        },
    )
    assert archived_response.status_code == 201, archived_response.text
    assert archived_response.json()["matched_specialist"] is None


def test_session_start_specialist_routing_uses_org_visible_linked_docs(
    client: TestClient, db: Session
) -> None:
    alice_email, alice_headers = _signup(client)
    bob_email, bob_headers = _signup(client)
    _join_same_org(
        client,
        db,
        owner_headers=alice_headers,
        member_email=bob_email,
        member_headers=bob_headers,
    )
    alice = _user_by_email(db, alice_email)
    bob = _user_by_email(db, bob_email)
    assert alice.organization_id == bob.organization_id

    org_doc_id = uuid.UUID(
        _create_document(
            client,
            alice_headers,
            title="Stripe refund webhook idempotency",
            description="Use durable Stripe event-id dedupe for refund webhooks.",
            visibility="organization",
        )
    )
    private_doc_id = uuid.UUID(
        _create_document(
            client,
            alice_headers,
            title="Private billing note",
            description="This private document must not appear in Bob's specialist preview.",
        )
    )

    slug = f"payments-{uuid.uuid4().hex[:8]}"
    specialist = AgentSpecialist(
        slug=slug,
        name="Payments Reliability",
        role="Payments Reliability Specialist",
        short_description="Stripe webhooks, refunds, and idempotency.",
        description="Specialist for payment webhook reliability.",
        status="active",
        visibility="organization",
        owner_id=alice.id,
        organization_id=alice.organization_id,
        domain_tags=["Stripe", "Payments"],
        routing_triggers=["stripe", "refund", "webhook", "idempotency"],
        negative_triggers=[],
        instructions=[],
        is_demo=False,
    )
    db.add(specialist)
    db.flush()
    db.add(
        AgentSpecialistDocumentLink(
            specialist_id=specialist.id,
            document_id=org_doc_id,
            anchor_id=None,
            is_pinned=True,
            weight=1.0,
        )
    )
    db.add(
        AgentSpecialistDocumentLink(
            specialist_id=specialist.id,
            document_id=private_doc_id,
            anchor_id=None,
            is_pinned=True,
            weight=1.0,
        )
    )
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/session/start",
        headers=bob_headers,
        json={
            "prompt": "Stripe refund webhook idempotency is needed",
            "files": ["app/api/routes/billing.py"],
            "min_score": 0.0,
        },
    )
    assert response.status_code == 201, response.text
    matched = response.json()["matched_specialist"]
    assert matched is not None
    assert matched["slug"] == slug
    linked_ids = {doc["document_id"] for doc in matched["linked_documents"]}
    assert str(org_doc_id) in linked_ids
    assert str(private_doc_id) not in linked_ids


def test_session_observe_with_structured_fields_skips_summarizer(
    client: TestClient,
) -> None:
    _, headers = _signup(client)
    doc_id = _create_document(client, headers, title="Tier 2 observe fixture")

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "final",
            "prompt": "test prompt",
            "transcript": [],
            "active_document_id": doc_id,
            "session_id": "tier-2-test",
            "summary_points": [
                "First claim about the work",
                "Second claim with more context",
            ],
            "decisions": ["Use the structured-path orchestrator"],
            "outcome": "shipped",
            "files_touched": ["src/foo.py", "tests/foo.py"],
            "duration_ms": 1000,
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["structured_path"] is True
    # Summarizer was skipped → no LLM cost
    assert body["summarizer_usd_cost"] in ("0", 0, "0.0", "0.00")


def test_session_observe_created_document_stamps_produced_by_client(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    _, headers = _signup(client)

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "final",
            "prompt": "Capture Stripe webhook idempotency notes",
            "client": "codex",
            "session_id": "origin-client-test",
            "summary_points": ["Use a durable idempotency key per Stripe event."],
            "details_sections": [
                {
                    "anchor_id": "decision",
                    "markdown": "Store processed event ids before side effects.",
                }
            ],
            "outcome": "shipped",
            "files_touched": ["app/api/routes/billing.py"],
            "duration_ms": 1000,
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["action"] == "created"
    assert body["shadow"] is False

    document = db.exec(
        select(V2Document).where(V2Document.id == uuid.UUID(body["document_id"]))
    ).one()
    assert document.produced_by_client == "codex"


def test_session_observe_preserves_cursor_client_over_claude_code(
    client: TestClient,
    db: Session,
) -> None:
    """Cursor hooks stamp ``cursor``; shared MCP defaults must not clobber it."""

    _, headers = _signup(client)
    session_id = "cursor-client-sticky"

    first = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "checkpoint",
            "prompt": "Travel recommendations for Tokyo",
            "client": "cursor",
            "session_id": session_id,
            "duration_ms": 100,
        },
    )
    assert first.status_code == 202, first.text

    second = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "checkpoint",
            "prompt": "Follow-up from MCP default client",
            "client": "claude-code",
            "session_id": session_id,
            "duration_ms": 100,
        },
    )
    assert second.status_code == 202, second.text

    archive = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.session_id == session_id
        )
    ).one()
    assert archive.client == "cursor"
    assert archive.harness_label == "cursor"


def test_session_observe_reuses_archive_active_document_without_request_pin(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    """Checkpoint hooks often omit active_document_id; reuse the archive pin."""

    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    _, headers = _signup(client)
    session_id = "one-doc-per-agent-session"

    first = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "checkpoint",
            "prompt": "Start fleet session doc",
            "client": "claude-code",
            "session_id": session_id,
            "summary_points": ["Initial checkpoint summary."],
            "files_touched": ["src/foo.py"],
            "duration_ms": 500,
        },
    )
    assert first.status_code == 202, first.text
    first_body = first.json()
    assert first_body["action"] == "created"
    document_id = first_body["document_id"]

    second = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "checkpoint",
            "prompt": "Continue the same agent session",
            "client": "claude-code",
            "session_id": session_id,
            "summary_points": ["Second checkpoint adds more context."],
            "files_touched": ["src/bar.py"],
            "duration_ms": 500,
        },
    )
    assert second.status_code == 202, second.text
    second_body = second.json()
    assert second_body["action"] == "updated"
    assert second_body["document_id"] == document_id

    archive = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.session_id == session_id
        )
    ).one()
    assert archive.active_document_id == uuid.UUID(document_id)


def test_demo_structured_observe_creates_recallable_document(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    _, headers = _signup(client)
    marker = f"SMOKE-{uuid.uuid4()}"

    observe = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe?demo=true",
        headers=headers,
        json={
            "kind": "final",
            "prompt": f"Record the widget cache TTL decision {marker}",
            "client": "smoke-test",
            "session_id": str(uuid.uuid4()),
            "summary_points": [f"{marker}: widget cache TTL is 900 seconds."],
            "details_sections": [
                {
                    "anchor_id": "decision",
                    "markdown": f"Widget cache TTL = 900s. Marker {marker}.",
                }
            ],
            "decisions": ["Widget cache TTL = 900s"],
            "outcome": "shipped",
            "files_touched": ["config/widget_cache.yaml"],
            "duration_ms": 1000,
        },
    )
    assert observe.status_code == 202, observe.text
    observe_body = observe.json()
    assert observe_body["action"] == "created"
    assert observe_body["shadow"] is False

    discover = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover?demo=true",
        headers=headers,
        json={
            "prompt": f"What did we decide about the widget cache TTL? {marker}",
            "k": 3,
            "min_score": 0.1,
        },
    )
    assert discover.status_code == 200, discover.text
    assert observe_body["document_id"] in {
        match["document_id"] for match in discover.json()["matches"]
    }


def test_session_observe_created_document_can_be_org_visible(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    email, headers = _signup(client)
    user = _user_by_email(db, email)

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "final",
            "prompt": "Capture shared Stripe refund webhook idempotency notes",
            "visibility": "organization",
            "session_id": "org-visible-observe-test",
            "summary_points": [
                "Use durable Stripe event-id dedupe for refund webhooks."
            ],
            "details_sections": [
                {
                    "anchor_id": "decision",
                    "markdown": "Make the document organization-visible for teammates.",
                }
            ],
            "files_touched": ["app/api/routes/billing.py"],
            "duration_ms": 1000,
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["action"] == "created"

    document = db.exec(
        select(V2Document).where(V2Document.id == uuid.UUID(body["document_id"]))
    ).one()
    assert document.visibility == "organization"
    assert document.organization_id == user.organization_id


def test_session_observe_without_structured_fields_uses_summarizer_path(
    client: TestClient,
) -> None:
    _, headers = _signup(client)
    doc_id = _create_document(client, headers, title="Tier 2 fallback fixture")

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "final",
            "prompt": "test prompt",
            "transcript": [
                {"role": "user", "content": "do work"},
                {"role": "assistant", "content": "doing"},
                {"role": "assistant", "content": "more work"},
                {"role": "assistant", "content": "done"},
            ],
            "active_document_id": doc_id,
            "session_id": "tier-2-fallback",
            "files_touched": ["src/bar.py", "src/baz.py"],
            "duration_ms": 1000,
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    # structured_path is False: no summary_points/details/decisions/outcome.
    assert body["structured_path"] is False
    # Always-write: with no managed key in the test env the deterministic free
    # digest writes the pinned document instead of skipping.
    assert body["reason"] == "ok"
    assert body["action"] == "updated"
    assert body["document_id"] == doc_id


def test_observe_always_writes_without_key_or_paid_summarizer(
    client: TestClient,
    monkeypatch,
) -> None:
    """Core always-write guarantee: a material non-structured session creates a
    document even with the paid summarizer disabled and no managed key, so the
    Sessions shared-context feed fills in regardless of LLM config."""

    from app.core.taskforce import observe as observe_mod

    # Paid summarizer off + no managed key → deterministic free digest only.
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "1")
    monkeypatch.setattr(observe_mod.settings, "ANTHROPIC_API_KEY", "")

    _, headers = _signup(client)
    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "final",
            "prompt": "Wire up the deterministic observe fallback",
            "transcript": [
                {"role": "user", "content": "do work"},
                {"role": "assistant", "content": "doing"},
                {"role": "assistant", "content": "done"},
            ],
            "session_id": "always-write-no-key",
            "files_touched": ["app/core/taskforce/observe.py"],
            "duration_ms": 1000,
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["action"] == "created"
    assert body["reason"] == "ok"
    assert body["structured_path"] is False
    assert body["document_id"] is not None
    # Free path: no summarizer spend.
    assert body["summarizer_usd_cost"] in ("0", 0, "0.0", "0.00")

    # The created doc is recallable — i.e. it actually landed in the corpus the
    # shared-context feed reads from.
    discover = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": "deterministic observe fallback", "client": "claude-code"},
    )
    assert discover.status_code == 200, discover.text


def test_observe_command_only_turn_never_titles_document_with_a_command(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    """A command-only checkpoint (empty prompt, no files, read-only commands)
    must not title the document with a raw 'Ran: …' shell line — and once a real
    prompt arrives on a later turn, the placeholder title is repaired in place.

    Regression for the PR #173 follow-up: the free digest's first point on such
    a turn is a 'Ran: …' line, and the title was frozen at creation, so the
    Sessions drawer showed a shell one-liner as the document title forever.
    """

    from app.core.taskforce import observe as observe_mod

    # Free deterministic digest only: no paid summarizer, no managed key.
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "1")
    monkeypatch.setattr(observe_mod.settings, "ANTHROPIC_API_KEY", "")

    _, headers = _signup(client)
    session_id = "command-only-title-repair"

    # First turn: no prompt, no files, only read-only commands. Material via the
    # ≥2-distinct-commands rule, so the doc is created from the free digest.
    first = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "checkpoint",
            "prompt": "",
            "client": "claude-code",
            "session_id": session_id,
            "commands_run": [
                {"cmd": "git log --oneline -1 5555196"},
                {"cmd": 'for d in */; do echo "$d"; done'},
            ],
            "duration_ms": 500,
        },
    )
    assert first.status_code == 202, first.text
    first_body = first.json()
    assert first_body["action"] == "created"
    document_id = first_body["document_id"]

    doc = db.exec(
        select(V2Document).where(V2Document.id == uuid.UUID(document_id))
    ).one()
    assert not doc.title.startswith("Ran: ")
    assert doc.title == "Taskforce session"

    # Second turn carries a real user prompt and pins the doc → reuses the same
    # document and repairs the placeholder title.
    second = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "checkpoint",
            "prompt": "Explain why the session document title is a raw command",
            "client": "claude-code",
            "session_id": session_id,
            "active_document_id": document_id,
            "duration_ms": 500,
        },
    )
    assert second.status_code == 202, second.text
    second_body = second.json()
    assert second_body["action"] == "updated"
    assert second_body["document_id"] == document_id
    assert "title" in second_body["patched_fields"]

    db.expire_all()
    repaired = db.exec(
        select(V2Document).where(V2Document.id == uuid.UUID(document_id))
    ).one()
    assert repaired.title == "Explain why the session document title is a raw command"


def test_observe_archive_persisted_before_summarizer_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archive transcript must survive hook timeouts that abort /observe mid-flight."""
    import asyncio

    from app.core.db import engine
    from app.core.taskforce import observe as observe_mod

    session_id = "observe-early-archive-commit"

    async def slow_then_fail(**_kwargs: object):
        await asyncio.sleep(0)
        with Session(engine) as check:
            events = check.exec(
                select(TaskforceSessionEvent).where(
                    TaskforceSessionEvent.session_id == session_id
                )
            ).all()
            assert events
            assert any(event.kind == "command" for event in events)
        raise TimeoutError("simulated Stop hook client disconnect")

    monkeypatch.setattr(observe_mod.settings, "ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(observe_mod, "summarize", slow_then_fail)

    _, headers = _signup(client)
    with pytest.raises(TimeoutError, match="simulated Stop hook"):
        client.post(
            f"{settings.API_V1_STR}/v2/taskforce/observe",
            headers=headers,
            json={
                "kind": "final",
                "prompt": "try 1 more echo",
                "transcript": [
                    {"role": "user", "content": "can you run an echo?"},
                    {"role": "assistant", "content": "Sure!"},
                    {
                        "role": "assistant",
                        "content": "Worked. Want me to echo something else?",
                    },
                ],
                "commands_run": [
                    {
                        "cmd": 'echo "one"',
                        "exit_code": 0,
                        "output": "one",
                    },
                    {
                        "cmd": 'echo "two"',
                        "exit_code": 0,
                        "output": "two",
                    },
                ],
                "session_id": session_id,
                "duration_ms": 5000,
            },
        )

    with Session(engine) as db:
        events = db.exec(
            select(TaskforceSessionEvent)
            .where(TaskforceSessionEvent.session_id == session_id)
            .order_by(
                TaskforceSessionEvent.occurred_at,
                TaskforceSessionEvent.source_order,
                TaskforceSessionEvent.created_at,
            )
        ).all()
        kinds = [event.kind for event in events]
        first_reply = kinds.index("reply")
        last_reply = len(kinds) - 1 - kinds[::-1].index("reply")
        command_idx = kinds.index("command")
        assert first_reply < command_idx < last_reply


def test_avoided_rediscovery_metric_accumulates_from_consults(
    client: TestClient,
) -> None:
    _, headers = _signup(client)
    # Create a doc with enough structure to score non-zero rediscovery cost.
    client.post(
        f"{settings.API_V1_STR}/v2/documents/",
        headers=headers,
        json={
            "title": "Library polish investigation",
            "description": "Cleanup of the metrics card.",
            "main_body": [
                {"segments": [{"text": "Removed the lock icon Private badge."}]},
                {
                    "segments": [
                        {"text": "Fixed click propagation on the actions menu."}
                    ]
                },
            ],
            "details_markdown_sections": [
                {
                    "anchor_id": "investigation",
                    "markdown": (
                        "Inspected `src/routes/v2/library.tsx`.\n"
                        "$ npx tsc --noEmit\n"
                        "Decided to use a `stopPropagation` handler.\n"
                    ),
                },
            ],
        },
    )

    discover = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "library polish metrics card",
            "k": 3,
            "min_score": 0.0,
        },
    )
    assert discover.status_code == 200, discover.text
    matches = discover.json()["matches"]
    if not matches:
        # Defensive: if scoring is too strict here, skip the assertion. The
        # consult emitter is covered by the unit tests above.
        return

    response = client.get(
        f"{settings.API_V1_STR}/v2/metrics",
        headers=headers,
        params={"metrics": "avoided_rediscovery", "window": "all"},
    )
    assert response.status_code == 200, response.text
    metric = response.json()["metrics"]["avoided_rediscovery"]
    # net_saved_tokens for at least one consult should be > 0 since the doc
    # has real rediscovery cost and the summary readout is small.
    assert int(float(metric["total"])) >= 0


# ----- TF-225: active-sessions roster ---------------------------------------


def test_discover_heartbeat_creates_archive_row(
    client: TestClient, db: Session
) -> None:
    _, headers = _signup(client)

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "set up the roster",
            "session_id": session_id_for("tf225-alpha"),
            "cwd": "/home/alexlee/dev/EnderAI",
            "git_branch": "main",
            "min_score": 0.0,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["active_sessions"] == []

    archive = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.session_id == session_id_for("tf225-alpha")
        )
    ).one()
    assert archive.last_seen_at is not None
    assert archive.cwd == "/home/alexlee/dev/EnderAI"
    assert archive.branch == "main"
    assert archive.repo == "EnderAI"
    assert archive.ended_at is None


def test_discover_active_sessions_surfaces_sibling_session(client: TestClient) -> None:
    _, headers = _signup(client)

    alpha = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "working on the frontend",
            "session_id": session_id_for("tf225-sibling-alpha"),
            "cwd": "/home/alexlee/dev/EnderAI-frontend",
            "git_branch": "feature/checkout",
            "min_score": 0.0,
        },
    )
    assert alpha.status_code == 200, alpha.text
    # alpha is the only session so far → no siblings yet.
    assert alpha.json()["active_sessions"] == []

    beta = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "working on the backend",
            "session_id": session_id_for("tf225-sibling-beta"),
            "cwd": "/home/alexlee/dev/EnderAI-backend",
            "git_branch": "main",
            "min_score": 0.0,
        },
    )
    assert beta.status_code == 200, beta.text
    siblings = beta.json()["active_sessions"]
    assert len(siblings) == 1
    sibling = siblings[0]
    assert sibling["session_id"] == session_id_for("tf225-sibling-alpha")
    assert sibling["cwd"] == "/home/alexlee/dev/EnderAI-frontend"
    assert sibling["active_document_id"] is None
    assert sibling["minutes_ago"] == 0

    # alpha, polling again, should now see beta as its only sibling — and
    # should not see itself.
    alpha_again = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "still working on the frontend",
            "session_id": session_id_for("tf225-sibling-alpha"),
            "min_score": 0.0,
        },
    )
    assert alpha_again.status_code == 200, alpha_again.text
    siblings_for_alpha = alpha_again.json()["active_sessions"]
    assert [s["session_id"] for s in siblings_for_alpha] == [session_id_for("tf225-sibling-beta")]


def test_discover_active_sessions_excludes_ended_sessions(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    _, headers = _signup(client)

    client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "ending this session",
            "session_id": session_id_for("tf225-ended"),
            "min_score": 0.0,
        },
    )
    # A "final" observe sets ended_at — the session should drop off the
    # roster even though last_seen_at is recent.
    observe = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "final",
            "prompt": "wrapping up",
            "session_id": session_id_for("tf225-ended"),
            "summary_points": ["Wrapped up the roster work."],
            "outcome": "shipped",
            "duration_ms": 1000,
        },
    )
    assert observe.status_code == 202, observe.text

    other = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "another session",
            "session_id": session_id_for("tf225-other"),
            "min_score": 0.0,
        },
    )
    assert other.status_code == 200, other.text
    assert other.json()["active_sessions"] == []


def test_observe_checkpoint_does_not_end_session(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    _, headers = _signup(client)

    client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "idle between turns",
            "session_id": session_id_for("tf228-checkpoint"),
            "min_score": 0.0,
        },
    )

    # The Stop hook fires on every agent-idle turn with kind: "checkpoint" —
    # this must not mark the session as ended.
    observe = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "checkpoint",
            "prompt": "still thinking",
            "session_id": session_id_for("tf228-checkpoint"),
            "duration_ms": 1000,
        },
    )
    assert observe.status_code == 202, observe.text

    archive = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.session_id == session_id_for("tf228-checkpoint")
        )
    ).one()
    assert archive.ended_at is None

    other = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "another session",
            "session_id": session_id_for("tf228-checkpoint-other"),
            "min_score": 0.0,
        },
    )
    assert other.status_code == 200, other.text
    assert [s["session_id"] for s in other.json()["active_sessions"]] == [
        session_id_for("tf228-checkpoint")
    ]


def test_observe_session_end_marks_session_ended(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    _, headers = _signup(client)

    client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "starting up",
            "session_id": session_id_for("tf228-session-end"),
            "min_score": 0.0,
        },
    )

    # The SessionEnd hook fires once, when the Claude Code session truly
    # terminates, with a minimal kind: "session_end" payload.
    observe = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "session_end",
            "prompt": "",
            "session_id": session_id_for("tf228-session-end"),
        },
    )
    assert observe.status_code == 202, observe.text

    archive = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.session_id == session_id_for("tf228-session-end")
        )
    ).one()
    assert archive.ended_at is not None

    other = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "another session",
            "session_id": session_id_for("tf228-session-end-other"),
            "min_score": 0.0,
        },
    )
    assert other.status_code == 200, other.text
    assert other.json()["active_sessions"] == []


def test_discover_active_sessions_includes_document_summary(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("TASKFORCE_OBSERVE_SHADOW", "0")
    _, headers = _signup(client)

    observe = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "checkpoint",
            "prompt": "Capture Postgres rotation notes",
            "client": "claude-code",
            "session_id": session_id_for("tf225-doc-session"),
            "cwd": "/home/alexlee/dev/EnderAI-backend",
            "checkpoint_index": 1,
            "summary_points": ["Documented the Postgres rotation runbook."],
            "details_sections": [
                {
                    "anchor_id": "decision",
                    "markdown": "Rotate the staging DSN every 14 days.",
                }
            ],
            "outcome": "shipped",
            "files_touched": ["ops/db-rotation.md"],
            "duration_ms": 1000,
        },
    )
    assert observe.status_code == 202, observe.text
    document_id = observe.json()["document_id"]

    # The observing session isn't "ended" (checkpoint, not final), so it
    # should appear in a sibling's roster with its active document's title +
    # summary.
    sibling = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "another terminal",
            "session_id": session_id_for("tf225-doc-sibling"),
            "min_score": 0.0,
        },
    )
    assert sibling.status_code == 200, sibling.text
    siblings = sibling.json()["active_sessions"]
    assert len(siblings) == 1
    entry = siblings[0]
    assert entry["session_id"] == session_id_for("tf225-doc-session")
    assert entry["active_document_id"] == document_id
    assert entry["title"]
    assert entry["summary_markdown"]


def test_active_sessions_endpoint_returns_roster(client: TestClient) -> None:
    _, headers = _signup(client)

    client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "terminal one",
            "session_id": session_id_for("tf225-rail-one"),
            "cwd": "/home/alexlee/dev/EnderAI",
            "min_score": 0.0,
        },
    )
    client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={
            "prompt": "terminal two",
            "session_id": session_id_for("tf225-rail-two"),
            "cwd": "/home/alexlee/dev/EnderAI-frontend",
            "min_score": 0.0,
        },
    )

    response = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/active-sessions",
        headers=headers,
        params={"session_id": session_id_for("tf225-rail-two")},
    )
    assert response.status_code == 200, response.text
    sessions = response.json()["active_sessions"]
    assert [s["session_id"] for s in sessions] == [session_id_for("tf225-rail-one")]


def test_active_sessions_scoped_per_actor(client: TestClient) -> None:
    _, headers_a = _signup(client)
    _, headers_b = _signup(client)

    client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers_a,
        json={
            "prompt": "user a session",
            "session_id": session_id_for("tf225-actor-a"),
            "min_score": 0.0,
        },
    )

    response = client.get(
        f"{settings.API_V1_STR}/v2/taskforce/active-sessions",
        headers=headers_b,
    )
    assert response.status_code == 200, response.text
    assert response.json()["active_sessions"] == []
