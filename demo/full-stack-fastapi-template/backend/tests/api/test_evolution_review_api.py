from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import AgentSpecialist
from tests.api.test_organizations_api import _signup
from tests.core.taskforce.test_evolution_doc_synthesis import _library_doc
from tests.utils.utils import random_lower_string

_REVIEW = f"{settings.API_V1_STR}/v2/evolution/review"


def test_review_queue_lists_proposed_specialist(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client, db, full_name="Review Queue User")
    actor = crud.get_user_by_email(session=db, email=email)
    assert actor is not None
    assert actor.organization_id is not None

    specialist = AgentSpecialist(
        owner_id=actor.id,
        organization_id=actor.organization_id,
        slug=f"proposed-{random_lower_string()}",
        name="Proposed Review",
        role="Earned pending",
        short_description="Awaiting confirm",
        status="proposed",
        visibility="organization",
        domain_tags=["billing"],
        routing_triggers=["billing"],
        instructions=[],
        created_from="earned",
        is_demo=False,
        evolution_provenance={"cluster_key": "billing", "source_session_ids": ["s1"]},
    )
    db.add(specialist)
    db.commit()

    response = client.get(_REVIEW, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert any(item["slug"] == specialist.slug for item in body["proposed_specialists"])


def test_confirm_proposed_specialist_activates_routing_status(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client, db, full_name="Confirm Specialist User")
    actor = crud.get_user_by_email(session=db, email=email)
    assert actor is not None

    specialist = AgentSpecialist(
        owner_id=actor.id,
        organization_id=actor.organization_id,
        slug=f"confirm-{random_lower_string()}",
        name="Confirm Me",
        role="Earned pending",
        short_description="",
        status="proposed",
        visibility="organization",
        domain_tags=[],
        routing_triggers=[],
        instructions=[],
        created_from="earned",
        is_demo=False,
    )
    db.add(specialist)
    db.commit()

    response = client.post(
        f"{_REVIEW}/specialists/{specialist.id}/confirm",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    db.refresh(specialist)
    assert specialist.status == "active"


def test_dismiss_document_contradiction_clears_stale_flag(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client, db, full_name="Dismiss Contradiction User")
    actor = crud.get_user_by_email(session=db, email=email)
    assert actor is not None

    document = _library_doc(
        db,
        actor,
        title="Contradiction flagged doc",
        body="Always use retry backoff",
    )
    document.evolution_stale = True
    document.evolution_provenance = {
        "curation_contradiction": {
            "source_session_id": "sess-x",
            "existing_phrase": "always",
            "incoming_phrase": "never",
        }
    }
    db.add(document)
    db.commit()

    response = client.post(
        f"{_REVIEW}/documents/{document.id}/dismiss-contradiction",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    db.refresh(document)
    assert document.evolution_stale is False
    assert "curation_contradiction" not in (document.evolution_provenance or {})
