import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session, col, select

from app.core.cases import build_case_public
from app.core.skills import build_skill_public, list_skill_models
from app.core.topics import (
    _case_visible_to_owner,
    build_topic_public_current,
    list_topic_models,
)
from app.models import (
    CasePublic,
    CaseRecord,
    SearchHitPublic,
    SearchResultsPublic,
    SearchRouteSearch,
    SkillPublic,
    TopicPublic,
)


@dataclass(slots=True)
class _ScoredHit:
    score: int
    hit: SearchHitPublic


def search_topics_and_cases(
    session: Session,
    q: str,
    *,
    owner_id: uuid.UUID,
    demo: bool = False,
    limit_per_kind: int = 5,
) -> SearchResultsPublic:
    query = _normalize_text(q)
    if len(query) < 2:
        raise ValueError("q must be at least 2 non-space characters")

    topics = list_topic_models(
        session,
        owner_id=owner_id,
        demo=demo,
        skip=0,
        limit=10_000,
    )
    topic_models = {topic.id: topic for topic in topics}
    cases = list(
        session.exec(
            select(CaseRecord).order_by(
                col(CaseRecord.updated_at).desc(),
                col(CaseRecord.opened_at).desc(),
            )
        ).all()
    )
    skills = list_skill_models(
        session,
        owner_id=owner_id,
        demo=demo,
        skip=0,
        limit=10_000,
    )

    topic_hits = [
        scored
        for topic in topics
        if (
            scored := _score_topic_hit(
                build_topic_public_current(
                    session,
                    topic,
                    owner_id=owner_id,
                    demo=demo,
                ),
                query,
            )
        )
        is not None
    ]
    case_hits = [
        scored
        for case_record in cases
        if (
            (topic := topic_models.get(case_record.topic_id)) is not None
            and _case_visible_to_owner(case_record, topic, owner_id)
            and (
                scored := _score_case_hit(
                    build_case_public(case_record, topic),
                    query,
                )
            )
            is not None
        )
    ]
    skill_hits = [
        scored
        for skill in skills
        if (scored := _score_skill_hit(build_skill_public(skill), query)) is not None
    ]

    _sort_hits(topic_hits)
    _sort_hits(case_hits)
    _sort_hits(skill_hits)

    return SearchResultsPublic(
        topics=[scored.hit for scored in topic_hits[:limit_per_kind]],
        cases=[scored.hit for scored in case_hits[:limit_per_kind]],
        skills=[scored.hit for scored in skill_hits[:limit_per_kind]],
        topic_count=len(topic_hits),
        case_count=len(case_hits),
        skill_count=len(skill_hits),
    )


def _sort_hits(hits: list[_ScoredHit]) -> None:
    hits.sort(
        key=lambda scored: (
            -scored.score,
            -(scored.hit.updated_at or datetime.min.replace(tzinfo=timezone.utc)).timestamp(),
            scored.hit.title.casefold(),
        )
    )


def _score_topic_hit(topic: TopicPublic, query: str) -> _ScoredHit | None:
    best = _best_group_match(
        query,
        (
            (topic.title, 900),
            (topic.workflow_key, 860),
            (_match_joined(topic.aliases), 760),
            (topic.description, 700),
            (topic.rollup_summary, 640),
            (_match_joined(topic.canonical_files), 600),
            (_match_joined(topic.canonical_symbols), 580),
            (_match_joined(topic.canonical_errors), 580),
            (_match_joined(topic.canonical_symptoms), 580),
            (_match_joined(topic.pinned_takeaways), 520),
            (_match_joined(topic.ambiguity_notes), 500),
            (_match_joined(topic.open_questions), 500),
            (_match_joined(topic.negative_history), 500),
            (_match_joined(topic.vocabulary), 420),
        ),
    )
    if best is None:
        return None

    score, excerpt = best
    return _ScoredHit(
        score=score,
        hit=SearchHitPublic(
            kind="topic",
            id=topic.id,
            title=topic.title,
            subtitle=topic.workflow_key,
            excerpt=excerpt,
            updated_at=topic.updated_at or topic.last_used_at,
            route="/topics",
            route_search=SearchRouteSearch(topicId=str(topic.id)),
        ),
    )


def _score_case_hit(case: CasePublic, query: str) -> _ScoredHit | None:
    command_values = [
        value
        for command in case.commands
        for value in (command.cmd, command.purpose, command.salient_result)
        if value
    ]
    hypothesis_values = [
        value
        for hypothesis in case.hypotheses
        for value in (hypothesis.statement, hypothesis.evidence)
        if value
    ]
    change_values = [
        value
        for change in case.changes
        for value in (*change.files, *change.refs, change.summary)
        if value
    ]
    snapshot = case.context_pack_snapshot
    relevant_case_values = [
        value
        for relevant_case in snapshot.relevant_cases
        for value in (
            relevant_case.title,
            relevant_case.short_summary,
            relevant_case.outcome,
            relevant_case.why_selected,
            *relevant_case.key_files,
            *relevant_case.key_symbols,
            *relevant_case.key_errors,
            *relevant_case.key_commands,
        )
        if value
    ]

    best = _best_group_match(
        query,
        (
            (case.title, 900),
            (case.topic_title, 760),
            (case.summary_current, 720),
            (case.input_summary, 700),
            (case.source, 320),
            (_match_joined(case.files), 620),
            (_match_joined(case.symbols), 600),
            (_match_joined(case.errors), 600),
            (_match_joined(case.symptoms), 600),
            (_match_joined(command_values), 540),
            (_match_joined(hypothesis_values), 520),
            (_match_joined(change_values), 500),
            (case.outcome, 480),
            (_match_joined(case.next_steps), 440),
            (snapshot.topic_summary, 420),
            (_match_joined(snapshot.matched_signals), 400),
            (_match_joined(snapshot.canonical_files), 380),
            (_match_joined(snapshot.canonical_symbols), 360),
            (_match_joined(snapshot.canonical_errors), 360),
            (_match_joined(snapshot.canonical_symptoms), 360),
            (_match_joined(snapshot.pinned_takeaways), 340),
            (_match_joined(snapshot.ambiguities), 320),
            (_match_joined(snapshot.questions), 320),
            (_match_joined(snapshot.negative_history), 320),
            (_match_joined(relevant_case_values), 300),
        ),
    )
    if best is None:
        return None

    score, excerpt = best
    return _ScoredHit(
        score=score,
        hit=SearchHitPublic(
            kind="case",
            id=case.id,
            title=case.title,
            subtitle=case.topic_title,
            excerpt=excerpt,
            updated_at=case.updated_at,
            route="/cases",
            route_search=SearchRouteSearch(caseId=str(case.id)),
        ),
    )


def _score_skill_hit(skill: SkillPublic, query: str) -> _ScoredHit | None:
    best = _best_group_match(
        query,
        (
            (skill.title, 900),
            (skill.slug, 860),
            (skill.description, 760),
            (_match_joined(skill.trigger_phrases), 700),
            (_match_joined(skill.files), 620),
            (_match_joined(skill.symbols), 600),
            (_match_joined(skill.errors), 600),
            (_match_joined(skill.symptoms), 600),
            (skill.instructions_md, 520),
        ),
    )
    if best is None:
        return None

    score, excerpt = best
    return _ScoredHit(
        score=score,
        hit=SearchHitPublic(
            kind="skill",
            id=skill.id,
            title=skill.title,
            subtitle=_skill_subtitle(skill),
            excerpt=excerpt,
            updated_at=skill.updated_at or skill.created_at,
            route="/skills",
            route_search=SearchRouteSearch(skillId=str(skill.id)),
        ),
    )


def _best_group_match(
    query: str,
    weighted_values: Iterable[tuple[str | None, int]],
) -> tuple[int, str | None] | None:
    best_score = 0
    best_excerpt: str | None = None

    for value, weight in weighted_values:
        score = _weighted_text_score(value, query, weight)
        if score <= best_score:
            continue
        best_score = score
        best_excerpt = _excerpt_for_value(value)

    if best_score <= 0:
        return None
    return best_score, best_excerpt


def _weighted_text_score(value: str | None, query: str, weight: int) -> int:
    normalized = _normalize_text(value)
    if not normalized:
        return 0

    if normalized == query:
        return weight + 120
    if normalized.startswith(query):
        return weight + 80
    if query in normalized:
        return weight + 40

    query_tokens = query.split()
    if query_tokens and all(token in normalized for token in query_tokens):
        return weight + 20
    return 0


def _match_joined(values: Iterable[str]) -> str | None:
    filtered = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    if not filtered:
        return None
    return "\n".join(filtered)


def _skill_subtitle(skill: SkillPublic) -> str:
    source_type = skill.source_type.replace("_", " ").title()
    return f"{source_type} skill"


def _excerpt_for_value(value: str | None) -> str | None:
    if not value:
        return None
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return None

    excerpt = lines[0]
    if len(excerpt) <= 140:
        return excerpt
    return excerpt[:137].rstrip() + "..."


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.casefold().split())
