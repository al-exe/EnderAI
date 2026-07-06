"""Per-session profile evolution (T4).

Evolve-on-use: when a material session used specialist S, compound S from that
session's learnings (doc links + instruction refresh). Orphan sessions with no
specialist feed proposed specialist birth once a domain cluster crosses N.

Runs offline only — called from ``evolution.evolve_session``, never routing.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from typing import Any

from sqlmodel import Session, col, select

from app.core.agents.compounding import (
    MIN_LINK_SCORE,
    _match_reason,
    link_document_to_specialist,
)
from app.core.taskforce.curation import evaluate_curation_gate
from app.core.taskforce.evolution_summary import (
    StoredEvolutionSummary,
    stored_summary_from_metadata,
)
from app.core.taskforce.scoring import DiscoveryRequest, score_document, tokenize
from app.models import (
    AgentSpecialist,
    TaskforceSessionArchive,
    User,
    V2Document,
    get_datetime_utc,
)

# Live orphan sessions sharing this domain signature propose one specialist.
CLUSTER_N = 3
# Demo orphans birth after a single session — a one-off demo run should produce a
# visible proposal (demo mode = the is_demo dataset the frontend toggle reveals).
DEMO_CLUSTER_N = 1

_SLUG_SPLIT = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    slug = _SLUG_SPLIT.sub("-", value.lower()).strip("-")
    return slug[:56] or "earned-profile"


def _unique_slug(session: Session, base: str) -> str:
    slug = base
    suffix = 2
    while (
        session.exec(
            select(AgentSpecialist).where(AgentSpecialist.slug == slug)
        ).first()
        is not None
    ):
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _cluster_key(stored: StoredEvolutionSummary, archive: TaskforceSessionArchive) -> str:
    tokens = tokenize(
        " ".join(stored.summary_points)
        or stored.outcome
        or (archive.title or "")
    )
    if not tokens:
        return "general"
    return "-".join(tokens[:3])


def _novel_instructions(
    specialist: AgentSpecialist, stored: StoredEvolutionSummary
) -> list[str]:
    existing = list(specialist.instructions or [])
    corpus = " ".join(existing).lower()
    novel: list[str] = []
    for decision in stored.decisions:
        stripped = decision.strip()
        if stripped and stripped.lower() not in corpus:
            novel.append(stripped[:240])
    if stored.outcome:
        outcome = stored.outcome.strip()
        if outcome and outcome.lower() not in corpus:
            novel.append(outcome[:240])
    for point in stored.summary_points[:2]:
        stripped = point.strip()
        if stripped and stripped.lower() not in corpus:
            novel.append(f"From session: {stripped[:200]}")
    return novel[:3]


def _specialist_for_archive(
    session: Session, archive: TaskforceSessionArchive
) -> AgentSpecialist | None:
    if not archive.specialist_slug or archive.organization_id is None:
        return None
    return session.exec(
        select(AgentSpecialist)
        .where(AgentSpecialist.slug == archive.specialist_slug)
        .where(AgentSpecialist.organization_id == archive.organization_id)
        .where(col(AgentSpecialist.is_demo).is_(False))
    ).first()


def _documents_to_link(
    session: Session,
    archive: TaskforceSessionArchive,
    *,
    docs_created: list[uuid.UUID],
    docs_updated: list[uuid.UUID],
) -> list[V2Document]:
    ids: list[uuid.UUID] = []
    if archive.active_document_id is not None:
        ids.append(archive.active_document_id)
    ids.extend(docs_created)
    ids.extend(docs_updated)
    seen: set[uuid.UUID] = set()
    documents: list[V2Document] = []
    for document_id in ids:
        if document_id in seen:
            continue
        seen.add(document_id)
        document = session.get(V2Document, document_id)
        if document is not None and not document.is_demo:
            documents.append(document)
    return documents


def evolve_profile_from_session(
    session: Session,
    *,
    archive: TaskforceSessionArchive,
    stored: StoredEvolutionSummary,
    docs_created: list[uuid.UUID],
    docs_updated: list[uuid.UUID],
) -> dict[str, Any]:
    """Compound the session's used specialist from this archive's learnings."""

    report: dict[str, Any] = {
        "specialist_slug": archive.specialist_slug,
        "links_created": 0,
        "links_updated": 0,
        "instructions_added": 0,
        "skipped": False,
    }
    specialist = _specialist_for_archive(session, archive)
    if specialist is None:
        report["skipped"] = True
        report["skip_reason"] = "no_specialist"
        return report
    if specialist.status != "active":
        report["skipped"] = True
        report["skip_reason"] = "specialist_not_active"
        return report

    gate = evaluate_curation_gate(action="update", stored=stored, match_score=0.0)
    if not gate.allowed:
        report["skipped"] = True
        report["skip_reason"] = gate.block_reason or "curation_blocked"
        return report

    actor = session.get(User, archive.actor_id)
    if actor is None:
        report["skipped"] = True
        report["skip_reason"] = "no_actor"
        return report

    request = DiscoveryRequest(
        prompt=" ".join(stored.summary_points) or (archive.title or ""),
        title=archive.title,
        git_branch=archive.branch,
        cwd=archive.cwd,
    )

    for document in _documents_to_link(
        session, archive, docs_created=docs_created, docs_updated=docs_updated
    ):
        scored = score_document(document, request)
        is_session_doc = archive.active_document_id == document.id
        effective_score = max(scored.score, stored.materiality_score if is_session_doc else 0.0)
        if effective_score < MIN_LINK_SCORE:
            continue
        reason = f"session {archive.session_id[:8]}: {_match_reason(specialist, document)}"
        created, updated = link_document_to_specialist(
            session,
            specialist,
            document,
            anchor_id=scored.matched_anchor_id,
            reason=reason[:240],
            weight=effective_score,
        )
        report["links_created"] += int(created)
        report["links_updated"] += int(updated)

    novel = _novel_instructions(specialist, stored)
    if novel:
        specialist.instructions = list(specialist.instructions or []) + novel
        report["instructions_added"] = len(novel)

    if specialist.created_from == "seeded" and (
        report["links_created"] or report["links_updated"]
    ):
        specialist.created_from = "earned"

    provenance = dict(specialist.evolution_provenance or {})
    provenance["last_session_evolution"] = {
        "source_session_id": archive.session_id,
        "confidence": gate.confidence,
        "links_created": report["links_created"],
        "links_updated": report["links_updated"],
        "instructions_added": report["instructions_added"],
    }
    specialist.evolution_provenance = provenance
    specialist.updated_at = get_datetime_utc()
    session.add(specialist)
    session.flush()
    report["specialist_id"] = str(specialist.id)
    return report


def _orphan_archives(
    session: Session, organization_id: uuid.UUID, *, demo: bool
) -> list[TaskforceSessionArchive]:
    return list(
        session.exec(
            select(TaskforceSessionArchive)
            .where(TaskforceSessionArchive.organization_id == organization_id)
            .where(col(TaskforceSessionArchive.is_demo).is_(demo))
            .where(col(TaskforceSessionArchive.specialist_slug).is_(None))
            .order_by(col(TaskforceSessionArchive.updated_at).desc())
            .limit(200)
        ).all()
    )


def _specialist_covers_cluster(
    session: Session,
    *,
    organization_id: uuid.UUID,
    cluster_key: str,
    demo: bool,
) -> bool:
    tokens = set(cluster_key.split("-"))
    specialists = session.exec(
        select(AgentSpecialist)
        .where(AgentSpecialist.organization_id == organization_id)
        .where(col(AgentSpecialist.is_demo).is_(demo))
        .where(col(AgentSpecialist.status).in_(("active", "proposed")))
    ).all()
    for specialist in specialists:
        signals = set(
            tokenize(" ".join([*(specialist.routing_triggers or []), *(specialist.domain_tags or [])]))
        )
        if tokens & signals:
            return True
    return False


def propose_specialists_from_orphans(
    session: Session,
    *,
    organization_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Birth proposed specialists from orphan session clusters (status=proposed).

    Runs two isolated ``is_demo`` scopes so demo and live never cross-contaminate:
    live orphans (``is_demo=False``) need ``CLUSTER_N`` sessions to birth a
    profile, while demo orphans (``is_demo=True``) birth after a single session
    (``DEMO_CLUSTER_N``) so a one-off demo run yields a visible proposal. Each born
    specialist inherits its scope's ``is_demo`` flag, keeping it inside the dataset
    the frontend demo-mode toggle shows or hides.
    """

    report: dict[str, Any] = {
        "clusters_seen": 0,
        "specialists_proposed": 0,
        "proposed_ids": [],
    }
    if organization_id is None:
        return report

    for demo, threshold in ((False, CLUSTER_N), (True, DEMO_CLUSTER_N)):
        _propose_scope(
            session,
            organization_id=organization_id,
            demo=demo,
            threshold=threshold,
            report=report,
        )
    return report


def _propose_scope(
    session: Session,
    *,
    organization_id: uuid.UUID,
    demo: bool,
    threshold: int,
    report: dict[str, Any],
) -> None:
    """Birth proposals for one ``is_demo`` scope; mutates ``report`` in place."""

    clusters: dict[str, list[tuple[TaskforceSessionArchive, StoredEvolutionSummary]]] = (
        defaultdict(list)
    )
    for archive in _orphan_archives(session, organization_id, demo=demo):
        stored = stored_summary_from_metadata(archive.source_metadata)
        if stored is None:
            continue
        gate = evaluate_curation_gate(action="create", stored=stored, match_score=0.0)
        if not gate.allowed:
            continue
        clusters[_cluster_key(stored, archive)].append((archive, stored))

    for cluster_key, members in clusters.items():
        if len(members) < threshold:
            continue
        report["clusters_seen"] += 1
        if _specialist_covers_cluster(
            session,
            organization_id=organization_id,
            cluster_key=cluster_key,
            demo=demo,
        ):
            continue

        existing_proposed = next(
            (
                row
                for row in session.exec(
                    select(AgentSpecialist)
                    .where(AgentSpecialist.organization_id == organization_id)
                    .where(col(AgentSpecialist.is_demo).is_(demo))
                    .where(AgentSpecialist.status == "proposed")
                ).all()
                if (row.evolution_provenance or {}).get("cluster_key") == cluster_key
            ),
            None,
        )
        if existing_proposed is not None:
            continue

        actor = session.get(User, members[0][0].actor_id)
        if actor is None:
            continue

        label = cluster_key.replace("-", " ").title()
        name = f"Earned {label}"[:80]
        slug = _unique_slug(session, _slugify(f"earned-{cluster_key}"))
        sample_points = [
            point
            for archive, stored in members
            for point in stored.summary_points[:1]
            if point.strip()
        ]
        short_description = (
            sample_points[0][:240]
            if sample_points
            else f"Earned from {len(members)} orphan sessions"
        )

        specialist = AgentSpecialist(
            owner_id=actor.id,
            organization_id=organization_id,
            slug=slug,
            name=name,
            role=f"Earned specialist for {label}"[:160],
            short_description=short_description,
            description=(
                f"Auto-proposed from {len(members)} sessions with no routed specialist."
            ),
            status="proposed",
            visibility="organization",
            domain_tags=[label],
            routing_triggers=list({token for token in cluster_key.split("-") if token}),
            negative_triggers=[],
            instructions=[
                "Review and confirm before routing — earned from orphan session cluster."
            ],
            created_from="earned",
            is_demo=demo,
            evolution_provenance={
                "cluster_key": cluster_key,
                "source_session_ids": [archive.session_id for archive, _ in members],
                "session_count": len(members),
                "confidence": members[0][1].materiality_score,
            },
        )
        session.add(specialist)
        session.flush()
        report["specialists_proposed"] += 1
        report["proposed_ids"].append(str(specialist.id))
