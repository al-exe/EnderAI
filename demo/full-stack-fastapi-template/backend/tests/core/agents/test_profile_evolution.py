from __future__ import annotations

from sqlmodel import Session, func, select

from app.core.agents.profile_evolution import (
    CLUSTER_N,
    DEMO_CLUSTER_N,
    evolve_profile_from_session,
    propose_specialists_from_orphans,
)
from app.core.taskforce.evolution_summary import (
    EVOLUTION_SUMMARY_KEY,
    StoredEvolutionSummary,
)
from app.models import (
    AgentSpecialist,
    AgentSpecialistDocumentLink,
    TaskforceSessionArchive,
    User,
)
from tests.core.agents.test_compounding import _document, _org, _org_user, _specialist
from tests.utils.utils import random_lower_string


def _archive(
    db: Session,
    user: User,
    *,
    summary_points: list[str],
    specialist_slug: str | None = None,
    active_document_id=None,
    demo: bool = False,
) -> TaskforceSessionArchive:
    archive = TaskforceSessionArchive(
        session_id=f"prof-{random_lower_string()}",
        actor_id=user.id,
        organization_id=user.organization_id,
        is_demo=demo,
        title=summary_points[0] if summary_points else "Session",
        specialist_slug=specialist_slug,
        active_document_id=active_document_id,
        source_metadata={
            EVOLUTION_SUMMARY_KEY: {
                "summary_points": summary_points,
                "details_sections": [],
                "decisions": ["Always verify webhook signatures"],
                "outcome": None,
                "materiality_score": 1.0,
            }
        },
    )
    db.add(archive)
    db.flush()
    return archive


def test_evolve_profile_links_session_doc_and_adds_instructions(db: Session) -> None:
    org = _org(db)
    user = _org_user(db, org)
    specialist = _specialist(db, user)
    document = _document(db, user)
    archive = _archive(
        db,
        user,
        summary_points=["Stripe webhook Billing retry guidance"],
        specialist_slug=specialist.slug,
        active_document_id=document.id,
    )
    stored = StoredEvolutionSummary(
        summary_points=["Stripe webhook Billing retry guidance"],
        details_sections=[],
        decisions=["Always verify webhook signatures"],
        outcome=None,
        materiality_score=1.0,
    )

    report = evolve_profile_from_session(
        db,
        archive=archive,
        stored=stored,
        docs_created=[],
        docs_updated=[],
    )

    assert report["skipped"] is False
    assert report["links_created"] >= 1
    assert report["instructions_added"] >= 1
    db.refresh(specialist)
    assert specialist.created_from == "earned"
    assert "Always verify webhook signatures" in specialist.instructions
    link_count = db.exec(
        select(func.count())
        .select_from(AgentSpecialistDocumentLink)
        .where(AgentSpecialistDocumentLink.specialist_id == specialist.id)
    ).one()
    assert link_count >= 1


def test_propose_specialist_from_orphan_cluster(db: Session) -> None:
    org = _org(db)
    user = _org_user(db, org)
    points = ["Stripe webhook Billing orphan cluster topic"]
    for _ in range(CLUSTER_N):
        _archive(db, user, summary_points=points, specialist_slug=None)

    report = propose_specialists_from_orphans(db, organization_id=org.id)
    assert report["specialists_proposed"] == 1
    proposed = db.exec(
        select(AgentSpecialist).where(AgentSpecialist.status == "proposed")
    ).all()
    assert len(proposed) == 1
    assert proposed[0].created_from == "earned"
    assert proposed[0].visibility == "organization"


def test_propose_demo_specialist_from_single_orphan(db: Session) -> None:
    # DEMO_CLUSTER_N == 1: a single demo orphan session births a proposal so a
    # one-off demo run is visible immediately.
    assert DEMO_CLUSTER_N == 1
    org = _org(db)
    user = _org_user(db, org)
    _archive(
        db,
        user,
        summary_points=["Kafka consumer lag demo orphan topic"],
        specialist_slug=None,
        demo=True,
    )

    report = propose_specialists_from_orphans(db, organization_id=org.id)
    assert report["specialists_proposed"] == 1
    # Scope to this test's org: the session-scoped db fixture accumulates rows
    # across tests in the module.
    proposed = db.exec(
        select(AgentSpecialist)
        .where(AgentSpecialist.organization_id == org.id)
        .where(AgentSpecialist.status == "proposed")
    ).all()
    assert len(proposed) == 1
    # Born into the demo dataset so the frontend demo-mode toggle governs it.
    assert proposed[0].is_demo is True
    assert proposed[0].created_from == "earned"


def test_single_live_orphan_does_not_propose(db: Session) -> None:
    # Live work still needs CLUSTER_N sessions — the lowered demo threshold must
    # not leak into real traffic.
    org = _org(db)
    user = _org_user(db, org)
    _archive(
        db,
        user,
        summary_points=["Postgres vacuum live orphan topic"],
        specialist_slug=None,
        demo=False,
    )

    report = propose_specialists_from_orphans(db, organization_id=org.id)
    assert report["specialists_proposed"] == 0
    # Scope the count to this test's org (session-scoped db accumulates rows).
    assert (
        db.exec(
            select(func.count())
            .select_from(AgentSpecialist)
            .where(AgentSpecialist.organization_id == org.id)
        ).one()
        == 0
    )


def test_proposed_specialist_does_not_route(db: Session) -> None:
    from app.core.agents.routing import route_specialist
    from app.core.taskforce.scoring import DiscoveryRequest

    org = _org(db)
    user = _org_user(db, org)
    specialist = AgentSpecialist(
        owner_id=user.id,
        organization_id=org.id,
        slug=f"proposed-only-{random_lower_string()}",
        name="Proposed Only",
        role="Pending review",
        short_description="Should not route yet",
        status="proposed",
        visibility="organization",
        domain_tags=["Stripe"],
        routing_triggers=["Stripe webhook"],
        instructions=[],
        created_from="earned",
        is_demo=False,
    )
    db.add(specialist)
    db.flush()

    matched = route_specialist(
        db,
        actor=user,
        request=DiscoveryRequest(prompt="Stripe webhook refund retries"),
        demo=False,
        min_band="low",
    )
    assert matched is None or matched.slug != specialist.slug
