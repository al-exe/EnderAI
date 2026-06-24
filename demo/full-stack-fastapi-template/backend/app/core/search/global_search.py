from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from sqlalchemy import String, cast, or_
from sqlmodel import Session, col, select

from app.core.agents.access import build_agent_specialist_acl_filter
from app.core.metrics.ledger import ledger_sessions
from app.core.search.legacy import search_topics_and_cases
from app.core.taskforce.active_sessions import (
    active_sessions_for_actor,
    history_agents_for_actor,
)
from app.core.v2_documents import build_v2_document_acl_filter
from app.models import (
    AgentSpecialist,
    SearchHitPublic,
    SearchResultsPublic,
    SearchRouteSearch,
    User,
    V2Document,
)


def search_global(
    session: Session,
    q: str,
    *,
    actor: User,
    demo: bool = False,
    limit_per_kind: int = 5,
) -> SearchResultsPublic:
    query = _normalize(q)
    if len(query) < 2:
        raise ValueError("q must be at least 2 non-space characters")

    legacy = search_topics_and_cases(
        session,
        query,
        owner_id=actor.id,
        demo=demo,
        limit_per_kind=limit_per_kind,
    )
    session_hits, session_count = _search_sessions(
        session, actor=actor, query=query, limit=limit_per_kind
    )
    profile_hits, profile_count = _search_profiles(
        session, actor=actor, demo=demo, query=query, limit=limit_per_kind
    )
    document_hits, document_count = _search_documents(
        session, actor=actor, demo=demo, query=query, limit=limit_per_kind
    )
    ledger_hits, ledger_count = _search_ledger(
        session, actor=actor, demo=demo, query=query, limit=limit_per_kind
    )

    return SearchResultsPublic(
        topics=legacy.topics,
        cases=legacy.cases,
        skills=legacy.skills,
        sessions=session_hits,
        profiles=profile_hits,
        documents=document_hits,
        ledger=ledger_hits,
        topic_count=legacy.topic_count,
        case_count=legacy.case_count,
        skill_count=legacy.skill_count,
        session_count=session_count,
        profile_count=profile_count,
        document_count=document_count,
        ledger_count=ledger_count,
    )


def _search_profiles(
    session: Session,
    *,
    actor: User,
    demo: bool,
    query: str,
    limit: int,
) -> tuple[list[SearchHitPublic], int]:
    like = _like(query)
    rows = list(
        session.exec(
            select(AgentSpecialist)
            .where(build_agent_specialist_acl_filter(actor, demo=demo))
            .where(
                or_(
                    col(AgentSpecialist.name).ilike(like, escape="\\"),
                    col(AgentSpecialist.slug).ilike(like, escape="\\"),
                    col(AgentSpecialist.role).ilike(like, escape="\\"),
                    col(AgentSpecialist.short_description).ilike(like, escape="\\"),
                    col(AgentSpecialist.description).ilike(like, escape="\\"),
                    cast(AgentSpecialist.domain_tags, String).ilike(like, escape="\\"),
                    cast(AgentSpecialist.routing_triggers, String).ilike(
                        like, escape="\\"
                    ),
                    cast(AgentSpecialist.negative_triggers, String).ilike(
                        like, escape="\\"
                    ),
                    cast(AgentSpecialist.instructions, String).ilike(like, escape="\\"),
                )
            )
        ).all()
    )
    scored = [
        (
            _score(
                query,
                (
                    (row.name, 900),
                    (row.slug, 860),
                    (row.role, 780),
                    (row.short_description, 720),
                    (row.description, 620),
                    (_joined(row.domain_tags), 580),
                    (_joined(row.routing_triggers), 560),
                    (_joined(row.negative_triggers), 500),
                    (_joined(row.instructions), 480),
                ),
            ),
            row,
        )
        for row in rows
    ]
    scored.sort(key=lambda item: _sort_key(item[0], item[1].updated_at, item[1].name))
    return (
        [
            SearchHitPublic(
                kind="profile",
                id=str(row.id),
                title=row.name,
                subtitle=row.role,
                excerpt=match[1] or row.short_description,
                updated_at=row.updated_at,
                route="/v2/profiles/$slug",
                href=f"/v2/profiles/{quote(row.slug, safe='')}",
                route_search=SearchRouteSearch(slug=row.slug),
            )
            for match, row in scored[:limit]
        ],
        len(scored),
    )


def _search_documents(
    session: Session,
    *,
    actor: User,
    demo: bool,
    query: str,
    limit: int,
) -> tuple[list[SearchHitPublic], int]:
    like = _like(query)
    rows = list(
        session.exec(
            select(V2Document)
            .where(build_v2_document_acl_filter(actor, demo=demo))
            .where(
                or_(
                    col(V2Document.title).ilike(like, escape="\\"),
                    col(V2Document.description).ilike(like, escape="\\"),
                    col(V2Document.human_summary).ilike(like, escape="\\"),
                    col(V2Document.ai_generated_summary).ilike(like, escape="\\"),
                    col(V2Document.details_file_name).ilike(like, escape="\\"),
                    cast(V2Document.collaborators, String).ilike(like, escape="\\"),
                    cast(V2Document.main_body, String).ilike(like, escape="\\"),
                    cast(V2Document.details_markdown_sections, String).ilike(
                        like, escape="\\"
                    ),
                )
            )
        ).all()
    )
    scored = [
        (
            _score(
                query,
                (
                    (row.title, 900),
                    (row.description, 760),
                    (row.human_summary, 720),
                    (row.ai_generated_summary, 700),
                    (row.details_file_name, 620),
                    (_joined(row.collaborators), 540),
                    (str(row.main_body), 460),
                    (str(row.details_markdown_sections), 440),
                ),
            ),
            row,
        )
        for row in rows
    ]
    scored.sort(key=lambda item: _sort_key(item[0], item[1].updated_at, item[1].title))
    return (
        [
            SearchHitPublic(
                kind="document",
                id=str(row.id),
                title=row.title,
                subtitle=row.details_file_name or "Library document",
                excerpt=match[1] or row.description or row.human_summary,
                updated_at=row.updated_at,
                route="/v2/library/$documentId",
                href=f"/v2/library/{row.id}",
                route_search=SearchRouteSearch(documentId=str(row.id)),
            )
            for match, row in scored[:limit]
        ],
        len(scored),
    )


def _search_sessions(
    session: Session,
    *,
    actor: User,
    query: str,
    limit: int,
) -> tuple[list[SearchHitPublic], int]:
    candidates = [
        *active_sessions_for_actor(session, actor=actor),
        *history_agents_for_actor(session, actor=actor),
    ]
    unique = {candidate.session_id: candidate for candidate in candidates}
    scored: list[tuple[tuple[int, str | None], Any]] = []
    for row in unique.values():
        match = _score(
            query,
            (
                (row.display_name, 900),
                (row.title, 840),
                (row.summary_markdown, 700),
                (row.cwd, 660),
                (row.specialist_slug, 620),
                (row.model_id, 600),
                (_joined(row.recent_activity), 720),
                (row.session_id, 540),
            ),
        )
        if match[0] > 0:
            scored.append((match, row))
    scored.sort(
        key=lambda item: _sort_key(item[0], item[1].last_seen_at, item[1].display_name)
    )
    return (
        [
            SearchHitPublic(
                kind="session",
                id=row.session_id,
                title=row.display_name,
                subtitle=f"{row.status.title()} · {row.agent_kind.title()}",
                excerpt=match[1] or row.title or row.summary_markdown,
                updated_at=row.last_seen_at,
                route="/v2/sessions/$sessionId",
                href=f"/v2/sessions/{quote(row.session_id, safe='')}",
                route_search=SearchRouteSearch(sessionId=row.session_id),
            )
            for match, row in scored[:limit]
        ],
        len(scored),
    )


def _search_ledger(
    session: Session,
    *,
    actor: User,
    demo: bool,
    query: str,
    limit: int,
) -> tuple[list[SearchHitPublic], int]:
    if actor.organization_id is None:
        return [], 0
    page = ledger_sessions(
        session,
        organization_id=actor.organization_id,
        is_demo=demo,
        query=query,
        limit=limit,
        offset=0,
    )
    return (
        [
            SearchHitPublic(
                kind="ledger",
                id=row.session_id,
                title=(
                    row.title
                    or (row.documents[0].title if row.documents else None)
                    or row.repo
                    or f"Session {row.session_id[:8]}"
                ),
                subtitle=" · ".join(
                    value
                    for value in (row.actor_name, row.client, row.specialist_name)
                    if value
                ),
                excerpt=" · ".join(
                    value
                    for value in (
                        row.repo,
                        row.branch,
                        ", ".join(doc.title for doc in row.documents[:3]),
                    )
                    if value
                ),
                updated_at=row.occurred_at_last,
                route="/v2/ledger",
                href=f"/v2/ledger?session_id={quote(row.session_id, safe='')}",
                route_search=SearchRouteSearch(sessionId=row.session_id),
            )
            for row in page.rows
        ],
        page.total,
    )


def _score(
    query: str, values: Iterable[tuple[str | None, int]]
) -> tuple[int, str | None]:
    best_score = 0
    best_excerpt: str | None = None
    for raw, weight in values:
        value = _normalize(raw)
        if not value:
            continue
        score = 0
        if value == query:
            score = weight + 120
        elif value.startswith(query):
            score = weight + 80
        elif query in value:
            score = weight + 40
        elif all(token in value for token in query.split()):
            score = weight + 20
        if score > best_score:
            best_score = score
            best_excerpt = _excerpt(raw)
    return best_score, best_excerpt


def _sort_key(
    match: tuple[int, str | None], updated_at: datetime | None, title: str
) -> tuple[int, float, str]:
    timestamp = (
        updated_at.timestamp()
        if updated_at is not None
        else datetime.min.replace(tzinfo=timezone.utc).timestamp()
    )
    return -match[0], -timestamp, title.casefold()


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _normalize(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _joined(values: Iterable[Any]) -> str | None:
    joined = "\n".join(str(value).strip() for value in values if str(value).strip())
    return joined or None


def _excerpt(value: str | None) -> str | None:
    lines = [line.strip() for line in (value or "").splitlines() if line.strip()]
    if not lines:
        return None
    text = lines[0]
    return text if len(text) <= 180 else f"{text[:177].rstrip()}..."
