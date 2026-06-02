from __future__ import annotations

import uuid

from sqlmodel import Session, func, select

from app.core.agents.compounding import compound_specialists
from app.core.agents.routing import route_specialist
from app.core.taskforce.scoring import DiscoveryRequest
from app.models import (
    AgentSpecialist,
    AgentSpecialistDocumentLink,
    Organization,
    User,
    V2Document,
)
from tests.utils.user import create_random_user
from tests.utils.utils import random_lower_string


def _org(db: Session) -> Organization:
    org = Organization(name=f"Compounding {random_lower_string()}")
    db.add(org)
    db.flush()
    return org


def _org_user(db: Session, org: Organization) -> User:
    user = create_random_user(db)
    user.organization_id = org.id
    user.organization_role = "admin"
    db.add(user)
    db.flush()
    return user


def _specialist(
    db: Session, user: User, *, suffix: str | None = None
) -> AgentSpecialist:
    specialist = AgentSpecialist(
        owner_id=user.id,
        organization_id=user.organization_id,
        slug=f"stripe-compound-{suffix or random_lower_string()}",
        name="Stripe Reliability",
        role="Billing reliability specialist",
        short_description="Stripe webhook idempotency and billing retries.",
        description="Handles Stripe billing reliability cases.",
        status="active",
        visibility="organization",
        domain_tags=["Billing"],
        routing_triggers=["Stripe webhook"],
        negative_triggers=[],
        instructions=["Check event-id idempotency before side effects."],
        created_from="seeded",
        is_demo=False,
    )
    db.add(specialist)
    db.flush()
    return specialist


def _document(
    db: Session,
    user: User,
    *,
    title: str = "Stripe webhook Billing",
    description: str = "Stripe webhook Billing event idempotency for refund retries.",
    visibility: str = "organization",
) -> V2Document:
    document = V2Document(
        owner_id=user.id,
        organization_id=user.organization_id,
        visibility=visibility,
        title=title,
        description=description,
        human_summary="Stripe webhook Billing idempotency prevents duplicate refunds.",
        ai_generated_summary="Stripe webhook Billing event ids must be durable.",
        collaborators=[],
        main_body=[
            {
                "segments": [
                    {
                        "text": (
                            "Persist Stripe webhook event ids before issuing "
                            "Billing refund side effects."
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
                    "Stripe webhook Billing retries should short-circuit "
                    "when the event id already exists."
                ),
            }
        ],
        is_demo=False,
    )
    db.add(document)
    db.flush()
    return document


def test_compound_specialists_dry_run_writes_nothing(db: Session) -> None:
    org = _org(db)
    user = _org_user(db, org)
    specialist = _specialist(db, user)
    _document(db, user)

    report = compound_specialists(db, organization_id=org.id, dry_run=True)

    assert report["specialists_seen"] == 1
    assert report["links_created"] == 1
    assert report["promoted_to_earned"] == 1
    assert specialist.created_from == "seeded"
    link_count = db.exec(
        select(func.count())
        .select_from(AgentSpecialistDocumentLink)
        .where(AgentSpecialistDocumentLink.specialist_id == specialist.id)
    ).one()
    assert link_count == 0


def test_compound_specialists_upserts_links_and_is_idempotent(db: Session) -> None:
    org = _org(db)
    user = _org_user(db, org)
    specialist = _specialist(db, user)
    document = _document(db, user)

    first = compound_specialists(db, organization_id=org.id, dry_run=False)
    db.flush()
    second = compound_specialists(db, organization_id=org.id, dry_run=False)

    assert first["specialists_seen"] == 1
    assert first["links_created"] == 1
    assert first["links_updated"] == 0
    assert first["promoted_to_earned"] == 1
    assert second["links_created"] == 0
    assert second["links_updated"] == 0
    assert second["promoted_to_earned"] == 0

    db.refresh(specialist)
    assert specialist.created_from == "earned"
    links = db.exec(
        select(AgentSpecialistDocumentLink).where(
            AgentSpecialistDocumentLink.specialist_id == specialist.id
        )
    ).all()
    assert len(links) == 1
    assert links[0].document_id == document.id
    assert links[0].anchor_id == "stripe-event-idempotency"
    assert links[0].reason == "earned: matched Stripe webhook, Billing"
    assert links[0].weight >= 0.45


def test_route_specialist_reads_earned_profile_without_special_case(
    db: Session,
) -> None:
    org = _org(db)
    user = _org_user(db, org)
    specialist = _specialist(db, user)
    _document(db, user)
    compound_specialists(db, organization_id=org.id, dry_run=False)
    db.flush()

    matched = route_specialist(
        db,
        actor=user,
        request=DiscoveryRequest(prompt="Stripe webhook refund retries"),
        demo=False,
        min_band="low",
    )

    assert matched is not None
    assert matched.specialist_id == specialist.id
    assert matched.slug == specialist.slug
    assert matched.linked_documents


def test_compound_specialists_prunes_lowest_weight_and_keeps_pinned(
    db: Session,
) -> None:
    org = _org(db)
    user = _org_user(db, org)
    specialist = _specialist(db, user)
    pinned_doc = _document(
        db,
        user,
        title=f"Pinned unrelated {uuid.uuid4()}",
        description="Keep this pinned curated context even when pruning.",
    )
    db.add(
        AgentSpecialistDocumentLink(
            specialist_id=specialist.id,
            document_id=pinned_doc.id,
            anchor_id="summary",
            reason="seeded curated context",
            weight=0.01,
            is_pinned=True,
        )
    )
    kept_doc = _document(db, user)
    _document(db, user, title="Stripe webhook retry")
    _document(db, user, title="Billing event idempotency")
    db.flush()

    report = compound_specialists(
        db,
        organization_id=org.id,
        max_links_per_specialist=2,
        dry_run=False,
    )
    db.flush()

    links = db.exec(
        select(AgentSpecialistDocumentLink).where(
            AgentSpecialistDocumentLink.specialist_id == specialist.id
        )
    ).all()

    assert report["links_pruned"] == 2
    assert len(links) == 2
    assert pinned_doc.id in {link.document_id for link in links}
    assert kept_doc.id in {link.document_id for link in links}
