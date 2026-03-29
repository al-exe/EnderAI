import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from sqlmodel import Session, col, or_, select

from app.core.cases import build_case_public
from app.models import (
    CasePublic,
    CaseRecord,
    ContextPackBuildRequest,
    ContextPackBuildResult,
    ContextPackSnapshot,
    RelevantCaseSummary,
    Topic,
    TopicHydrationPolicy,
    TopicMatchCandidate,
    TopicMatchRequest,
    TopicMatchResult,
    TopicPublic,
    TopicRollupPublic,
    get_datetime_utc,
)

TOKEN_RE = re.compile(r"[a-z0-9_./-]+")


def allocate_topic_identity(
    session: Session,
    title: str,
    workflow_key: str | None,
) -> tuple[str, str]:
    base_workflow_key = _slugify(workflow_key or title)
    workflow_candidate = base_workflow_key
    suffix = 2
    while _topic_exists_with_workflow_key(session, workflow_candidate):
        workflow_candidate = f"{base_workflow_key}-{suffix}"
        suffix += 1

    base_slug = _slugify(title)
    slug_candidate = base_slug
    suffix = 2
    while _topic_exists_with_slug(session, slug_candidate):
        slug_candidate = f"{base_slug}-{suffix}"
        suffix += 1

    return slug_candidate, workflow_candidate


def build_topic_public(topic: Topic) -> TopicPublic:
    rollup = build_topic_rollup_public(topic)
    return TopicPublic(
        id=topic.id,
        title=topic.title,
        slug=topic.slug,
        description=_clean_optional_string(topic.description),
        aliases=_canonical_topic_aliases([*(_string_list(topic.aliases)), *rollup.aliases], topic),
        status=_clean_optional_string(topic.status) or "open",
        workflow_key=topic.workflow_key,
        owner_ids=_uuid_list(topic.owner_ids),
        created_at=topic.created_at,
        updated_at=topic.updated_at,
        last_used_at=topic.last_used_at,
        rollup_summary=topic.rollup_summary or rollup.brief,
        rollup_version=topic.rollup_version,
        canonical_files=rollup.canonical_files,
        canonical_symbols=rollup.canonical_symbols,
        canonical_errors=rollup.canonical_errors,
        canonical_symptoms=rollup.canonical_symptoms,
        pinned_takeaways=rollup.pinned_takeaways,
        ambiguity_notes=rollup.ambiguity_notes,
        open_questions=rollup.open_questions,
        negative_history=rollup.negative_history,
        representative_case_ids=rollup.representative_case_ids,
        recent_case_ids=rollup.recent_case_ids,
        vocabulary=rollup.vocabulary,
        case_count=rollup.case_count,
    )


def build_topic_rollup_public(topic: Topic) -> TopicRollupPublic:
    rollup_payload = _default_rollup(topic)
    rollup_payload.update(_json_object(topic.rollup_data))
    rollup_payload["aliases"] = _canonical_topic_aliases(
        _string_list(rollup_payload.get("aliases")),
        topic,
    )
    return TopicRollupPublic(**rollup_payload)


def build_topic_public_current(
    session: Session,
    topic: Topic,
    *,
    owner_id: uuid.UUID | None = None,
    demo: bool = False,
) -> TopicPublic:
    if owner_id is not None:
        rollup = refresh_topic_rollup(
            session,
            topic.id,
            persist=False,
            owner_id=owner_id,
            demo=demo,
        )
        if rollup is None:
            return build_topic_public(topic)

        refreshed_topic = Topic(**topic.model_dump(mode="python"))
        refreshed_topic.rollup_summary = rollup.brief
        refreshed_topic.rollup_data = rollup.model_dump(mode="json")
        return build_topic_public(refreshed_topic)

    if not _topic_rollup_needs_refresh(session, topic):
        return build_topic_public(topic)

    rollup = refresh_topic_rollup(session, topic.id, persist=False, demo=demo)
    if rollup is None:
        return build_topic_public(topic)

    refreshed_topic = Topic(**topic.model_dump(mode="python"))
    refreshed_topic.rollup_summary = rollup.brief
    refreshed_topic.rollup_data = rollup.model_dump(mode="json")
    return build_topic_public(refreshed_topic)


def list_topic_models(
    session: Session,
    *,
    owner_id: uuid.UUID | None = None,
    demo: bool = False,
    status: str | None = None,
    q: str | None = None,
    workflow_key: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Topic]:
    statement = select(Topic)
    if status:
        statement = statement.where(Topic.status == status.strip())
    if workflow_key:
        statement = statement.where(Topic.workflow_key == workflow_key.strip())
    if q:
        like = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Topic.title.ilike(like),
                Topic.workflow_key.ilike(like),
                Topic.description.ilike(like),
            )
        )
    statement = statement.order_by(col(Topic.last_used_at).desc(), col(Topic.updated_at).desc())
    topics = list(session.exec(statement).all())
    if owner_id is not None:
        actor_topic_ids = _topic_ids_with_owned_cases(session, owner_id)
        topics = [
            topic
            for topic in topics
            if _topic_visible_to_owner(topic, owner_id, actor_topic_ids=actor_topic_ids)
        ]
    topics = [topic for topic in topics if _topic_matches_demo_mode(topic, demo)]
    return topics[skip : skip + limit]


def count_topics(
    session: Session,
    *,
    owner_id: uuid.UUID | None = None,
    demo: bool = False,
    status: str | None = None,
    q: str | None = None,
    workflow_key: str | None = None,
) -> int:
    return len(
        list_topic_models(
            session,
            owner_id=owner_id,
            demo=demo,
            status=status,
            q=q,
            workflow_key=workflow_key,
            skip=0,
            limit=10_000,
        )
    )


def read_topic_model(
    session: Session,
    topic_id: uuid.UUID,
    owner_id: uuid.UUID | None = None,
    *,
    demo: bool = False,
    claim_legacy_orphans: bool = False,
) -> Topic | None:
    topic = session.get(Topic, topic_id)
    if topic is None:
        return None
    if not _topic_matches_demo_mode(topic, demo):
        return None
    if owner_id is not None and not _topic_visible_to_owner(topic, owner_id, session=session):
        if claim_legacy_orphans:
            claimed = claim_legacy_orphan_topics_for_owner(
                session,
                owner_id,
                topic_id=topic_id,
            )
            if claimed:
                session.flush()
                topic = session.get(Topic, topic_id)
        if (
            topic is None
            or not _topic_matches_demo_mode(topic, demo)
            or not _topic_visible_to_owner(topic, owner_id, session=session)
        ):
            return None
    return topic


def list_cases_for_topic(
    session: Session,
    topic_id: uuid.UUID,
    owner_id: uuid.UUID | None = None,
    demo: bool = False,
) -> list[CasePublic]:
    topic = read_topic_model(session, topic_id, owner_id=owner_id, demo=demo)
    if topic is None:
        return []

    statement = (
        select(CaseRecord)
        .where(CaseRecord.topic_id == topic_id)
        .order_by(col(CaseRecord.updated_at).desc(), col(CaseRecord.opened_at).desc())
    )
    rows = list(session.exec(statement).all())
    if owner_id is not None:
        rows = [
            row
            for row in rows
            if _case_visible_to_owner(row, topic, owner_id)
        ]
    return [build_case_public(row, topic) for row in rows]


def refresh_topic_rollup(
    session: Session,
    topic_id: uuid.UUID,
    *,
    persist: bool = True,
    owner_id: uuid.UUID | None = None,
    demo: bool = False,
) -> TopicRollupPublic | None:
    topic = read_topic_model(session, topic_id, owner_id=owner_id, demo=demo)
    if topic is None:
        return None

    should_persist = persist and owner_id is None
    existing_rollup = build_topic_rollup_public(topic)
    cases = list_cases_for_topic(session, topic_id, owner_id=owner_id, demo=demo)

    file_counts: Counter[str] = Counter()
    symbol_counts: Counter[str] = Counter()
    error_counts: Counter[str] = Counter()
    symptom_counts: Counter[str] = Counter()
    vocabulary_counts: Counter[str] = Counter()
    outcome_candidates: list[str] = []
    open_questions: list[str] = []
    pinned_takeaways: list[str] = []
    negative_history: list[str] = []
    aliases = _dedupe_preserve_order(list(topic.aliases))

    for case in cases:
        file_counts.update(case.files)
        for change in case.changes:
            file_counts.update(change.files)
        symbol_counts.update(case.symbols)
        error_counts.update(case.errors)
        symptom_counts.update(case.symptoms)
        vocabulary_counts.update(_tokens_from_case(case))
        if case.outcome:
            outcome_candidates.append(case.outcome)
            pinned_takeaways.append(case.outcome)
        for hypothesis in case.hypotheses:
            if hypothesis.status == "supported":
                pinned_takeaways.append(hypothesis.statement)
            if hypothesis.status == "open":
                open_questions.append(hypothesis.statement)
            if hypothesis.status == "disproven":
                negative_history.append(hypothesis.statement)
        summary_text = case.summary_current or case.title
        if summary_text:
            aliases.extend(_tokens(summary_text)[:2])

    if not cases:
        open_questions = list(existing_rollup.open_questions)
        pinned_takeaways = list(existing_rollup.pinned_takeaways)
        negative_history = list(existing_rollup.negative_history)
        aliases = _dedupe_preserve_order([*aliases, *existing_rollup.aliases])

    recent_cases = [case.id for case in cases[:5]]
    representative_cases = [case.id for case in sorted(cases, key=_representative_case_key, reverse=True)[:3]]
    updated_at = cases[0].updated_at if cases else topic.updated_at
    latest_summary = cases[0].summary_current if cases else None
    brief = latest_summary or (outcome_candidates[0] if outcome_candidates else existing_rollup.brief or topic.title)
    vocabulary = _top_keys(vocabulary_counts, limit=20) if cases else existing_rollup.vocabulary

    rollup = TopicRollupPublic(
        brief=brief,
        canonical_files=_top_keys(file_counts),
        canonical_symbols=_top_keys(symbol_counts),
        canonical_errors=_top_keys(error_counts),
        canonical_symptoms=_top_keys(symptom_counts),
        pinned_takeaways=_dedupe_preserve_order(pinned_takeaways)[:10],
        negative_history=_dedupe_preserve_order(negative_history)[:10],
        representative_case_ids=representative_cases,
        aliases=_canonical_topic_aliases(aliases, topic)[:12],
        vocabulary=vocabulary,
        ambiguity_notes=existing_rollup.ambiguity_notes,
        open_questions=_dedupe_preserve_order(open_questions)[:10],
        case_count=len(cases),
        recent_case_ids=recent_cases,
        updated_at=updated_at,
    )

    if should_persist:
        topic.rollup_summary = rollup.brief
        topic.rollup_data = rollup.model_dump(mode="json")
        topic.updated_at = get_datetime_utc()
        session.add(topic)
    return rollup


def match_topics(
    session: Session,
    request: TopicMatchRequest,
    *,
    owner_id: uuid.UUID | None = None,
    demo: bool = False,
) -> TopicMatchResult:
    topics = [
        build_topic_public_current(session, topic, owner_id=owner_id, demo=demo)
        for topic in list_topic_models(session, owner_id=owner_id, demo=demo)
    ]
    candidates = [_score_topic_match(topic, request) for topic in topics]
    candidates = [candidate for candidate in candidates if candidate.score > 0]
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    candidates = candidates[: max(request.limit, 1)]
    policy = _policy_for_candidates(candidates)
    return TopicMatchResult(policy=policy, candidates=candidates)


def build_context_pack(
    session: Session,
    request: ContextPackBuildRequest,
    *,
    owner_id: uuid.UUID | None = None,
    demo: bool = False,
) -> ContextPackBuildResult:
    if request.topic_id is not None:
        topic_model = read_topic_model(
            session,
            request.topic_id,
            owner_id=owner_id,
            demo=demo,
        )
        if topic_model is None:
            raise ValueError("Topic not found")
        topic = build_topic_public_current(
            session,
            topic_model,
            owner_id=owner_id,
            demo=demo,
        )
        policy = TopicHydrationPolicy(confidence="high", max_topics=1)
        matched_topics = [
            TopicMatchCandidate(
                topic=topic,
                score=100.0,
                confidence="high",
                matched_signals=[],
                reasoning=["topic_id explicitly selected"],
            )
        ]
    else:
        match_result = match_topics(
            session,
            TopicMatchRequest(
                title=request.title,
                request_summary=request.request_summary,
                aliases=request.aliases,
                files=request.files,
                symbols=request.symbols,
                errors=request.errors,
                symptoms=request.symptoms,
                contexts=request.contexts,
                limit=request.max_topics or 5,
            ),
            owner_id=owner_id,
            demo=demo,
        )
        policy = match_result.policy
        matched_topics = match_result.candidates

    max_topics = request.max_topics or policy.max_topics
    selected_topics = matched_topics[:max_topics]

    selected_case_ids: list[uuid.UUID] = []
    representative_cases: list[uuid.UUID] = []
    recent_cases: list[uuid.UUID] = []
    relevant_cases: list[RelevantCaseSummary] = []
    canonical_files: list[str] = []
    canonical_symbols: list[str] = []
    canonical_errors: list[str] = []
    canonical_symptoms: list[str] = []
    pinned_takeaways: list[str] = []
    ambiguities: list[str] = []
    questions: list[str] = []
    negative_history: list[str] = []
    matched_signals: list[str] = []

    for candidate in selected_topics:
        topic = candidate.topic
        matched_signals.extend(candidate.matched_signals)
        canonical_files.extend(topic.canonical_files)
        canonical_symbols.extend(topic.canonical_symbols)
        canonical_errors.extend(topic.canonical_errors)
        canonical_symptoms.extend(topic.canonical_symptoms)
        pinned_takeaways.extend(topic.pinned_takeaways)
        ambiguities.extend(topic.ambiguity_notes)
        questions.extend(topic.open_questions)
        negative_history.extend(topic.negative_history)
        topic_cases = list_cases_for_topic(
            session,
            topic.id,
            owner_id=owner_id,
            demo=demo,
        )
        ranked_cases = sorted(
            topic_cases,
            key=lambda case: _score_case_for_request(case, request),
            reverse=True,
        )
        picked_cases = ranked_cases[: max(request.max_cases_per_topic, 1)]
        topic_relevant_cases = [
            _build_relevant_case_summary(case, request, topic.title) for case in picked_cases
        ]
        relevant_cases.extend(topic_relevant_cases)
        selected_case_ids.extend(summary.case_id for summary in topic_relevant_cases)
        representative_cases.extend(
            topic.representative_case_ids or [summary.case_id for summary in topic_relevant_cases]
        )
        recent_cases.extend(topic.recent_case_ids)

    relevant_cases = _dedupe_relevant_cases(relevant_cases)
    primary_topic = selected_topics[0].topic if selected_topics else None
    now = datetime.now(timezone.utc)
    alternative_topic_ids = [
        candidate.topic.id
        for candidate in matched_topics
        if primary_topic is None or candidate.topic.id != primary_topic.id
    ]
    snapshot = ContextPackSnapshot(
        topic_id=primary_topic.id if primary_topic else None,
        confidence=policy.confidence,
        alternative_topic_ids=_dedupe_preserve_order(alternative_topic_ids)[:4],
        topic_summary=primary_topic.rollup_summary if primary_topic else None,
        matched_signals=_dedupe_preserve_order(matched_signals)[:10],
        representative_cases=_dedupe_preserve_order(representative_cases)[:8],
        recent_cases=_dedupe_preserve_order(recent_cases)[:8],
        relevant_cases=relevant_cases[:8],
        canonical_files=_dedupe_preserve_order(canonical_files)[:10],
        canonical_symbols=_dedupe_preserve_order(canonical_symbols)[:10],
        canonical_errors=_dedupe_preserve_order(canonical_errors)[:10],
        canonical_symptoms=_dedupe_preserve_order(canonical_symptoms)[:10],
        pinned_takeaways=_dedupe_preserve_order(pinned_takeaways)[:10],
        ambiguities=_dedupe_preserve_order(ambiguities)[:10],
        questions=_dedupe_preserve_order(questions)[:10],
        negative_history=_dedupe_preserve_order(negative_history)[:10],
        builder_version="v1",
        created_at=now,
    )

    return ContextPackBuildResult(
        policy=policy,
        matched_topics=selected_topics,
        selected_topic_ids=[candidate.topic.id for candidate in selected_topics],
        selected_case_ids=_dedupe_preserve_order(selected_case_ids),
        relevant_cases=relevant_cases,
        context_pack_snapshot=snapshot,
    )


def _default_rollup(topic: Topic) -> dict[str, Any]:
    return {
        "brief": topic.rollup_summary or topic.title,
        "canonical_files": [],
        "canonical_symbols": [],
        "canonical_errors": [],
        "canonical_symptoms": [],
        "pinned_takeaways": [],
        "negative_history": [],
        "representative_case_ids": [],
        "aliases": list(topic.aliases),
        "vocabulary": _tokens(topic.title),
        "ambiguity_notes": [],
        "open_questions": [],
        "case_count": 0,
        "recent_case_ids": [],
        "updated_at": topic.updated_at,
    }


def _topic_ids_with_owned_cases(session: Session, owner_id: uuid.UUID) -> set[uuid.UUID]:
    statement = select(CaseRecord.topic_id).where(CaseRecord.actor_id == owner_id)
    return set(session.exec(statement).all())


def claim_legacy_orphan_topics_for_owner(
    session: Session,
    owner_id: uuid.UUID,
    *,
    topic_id: uuid.UUID | None = None,
) -> int:
    # Compatibility bridge for rows created before ownership metadata was enforced.
    # Once claimed, the topic/cases behave like normal owned data.
    owner_id_str = str(owner_id)
    now = get_datetime_utc()
    claimed_topics = 0

    if topic_id is not None:
        topics = [session.get(Topic, topic_id)]
    else:
        topics = list(session.exec(select(Topic)).all())

    for topic in topics:
        if topic is None:
            continue
        if owner_id_str in topic.owner_ids:
            continue
        if topic.owner_ids:
            continue

        cases = list(
            session.exec(
                select(CaseRecord).where(CaseRecord.topic_id == topic.id)
            ).all()
        )
        if any(case.actor_id not in {None, owner_id} for case in cases):
            continue

        topic.owner_ids = [owner_id_str]
        topic.updated_at = now
        session.add(topic)
        claimed_topics += 1

        for case in cases:
            if case.actor_id is None:
                case.actor_id = owner_id
                case.updated_at = now
                session.add(case)

    return claimed_topics


def _topic_visible_to_owner(
    topic: Topic,
    owner_id: uuid.UUID,
    *,
    session: Session | None = None,
    actor_topic_ids: set[uuid.UUID] | None = None,
) -> bool:
    owner_id_str = str(owner_id)
    if owner_id_str in topic.owner_ids:
        return True
    if actor_topic_ids is None:
        if session is None:
            return False
        actor_topic_ids = _topic_ids_with_owned_cases(session, owner_id)
    return topic.id in actor_topic_ids


def _topic_matches_demo_mode(topic: Topic, demo: bool) -> bool:
    return topic.is_demo if demo else not topic.is_demo


def _case_visible_to_owner(case: CaseRecord, topic: Topic, owner_id: uuid.UUID) -> bool:
    if case.actor_id == owner_id:
        return True
    return case.actor_id is None and str(owner_id) in topic.owner_ids


def _score_topic_match(topic: TopicPublic, request: TopicMatchRequest) -> TopicMatchCandidate:
    matched_signals: list[str] = []
    reasoning: list[str] = []
    score = 0.0

    request_fragments = _request_text_fragments(request)
    request_text = _request_search_text(request)
    request_tokens = set(_tokens(request_text))
    topic_tokens = set(
        _tokens(
            " ".join(
                [
                    topic.title,
                    topic.workflow_key,
                    topic.description or "",
                    topic.rollup_summary or "",
                    *topic.aliases,
                    *topic.vocabulary,
                    *topic.canonical_files,
                    *topic.canonical_symbols,
                    *topic.canonical_errors,
                    *topic.canonical_symptoms,
                    *_topic_file_hint_tokens(topic),
                ]
            )
        )
    )
    token_overlap = sorted(request_tokens & topic_tokens)
    if token_overlap:
        score += min(5.0, float(len(token_overlap)))
        matched_signals.extend(token_overlap[:4])
        reasoning.append(f"token overlap: {', '.join(token_overlap[:4])}")

    score += _score_text_similarity(request_fragments, topic, reasoning)
    score += _score_file_overlap(request.files, topic.canonical_files, matched_signals, reasoning)
    score += _score_overlap(request.symbols, topic.canonical_symbols, matched_signals, reasoning, "symbols")
    score += _score_overlap(request.errors, topic.canonical_errors, matched_signals, reasoning, "errors")
    score += _score_overlap(request.symptoms, topic.canonical_symptoms, matched_signals, reasoning, "symptoms")
    score += _score_context_overlap(request.contexts, topic, matched_signals, reasoning)

    alias_overlap = _dedupe_preserve_order(request.aliases + ([request.title] if request.title else []))
    alias_hits = _match_values(alias_overlap, topic.aliases)
    if alias_hits:
        score += 2.5
        matched_signals.extend(alias_hits)
        reasoning.append(f"alias/title match: {', '.join(alias_hits[:3])}")

    if topic.last_used_at is not None:
        last_used_at = _coerce_utc_datetime(topic.last_used_at)
        recent_days = (datetime.now(timezone.utc) - last_used_at).days
        if recent_days <= 30:
            score += 1.0
            reasoning.append("recent activity bonus")

    confidence = _confidence_for_score(score)
    return TopicMatchCandidate(
        topic=topic,
        score=round(score, 2),
        confidence=confidence,
        matched_signals=_dedupe_preserve_order(matched_signals)[:8],
        reasoning=reasoning,
    )


def _policy_for_candidates(candidates: list[TopicMatchCandidate]) -> TopicHydrationPolicy:
    if not candidates:
        return TopicHydrationPolicy(confidence="low", max_topics=1)

    top = candidates[0].score
    second = candidates[1].score if len(candidates) > 1 else 0.0
    if top >= 7.0 and top - second >= 1.5:
        return TopicHydrationPolicy(confidence="high", max_topics=1)
    if top >= 3.5:
        return TopicHydrationPolicy(confidence="medium", max_topics=min(3, len(candidates)))
    return TopicHydrationPolicy(confidence="low", max_topics=min(5, len(candidates)))


def _score_overlap(
    request_values: list[str],
    topic_values: list[str],
    matched_signals: list[str],
    reasoning: list[str],
    label: str,
) -> float:
    overlap = _match_values(request_values, topic_values)
    if not overlap:
        return 0.0
    matched_signals.extend(overlap)
    reasoning.append(f"{label} overlap: {', '.join(overlap[:3])}")
    return min(4.0, len(overlap) * 2.0)


def _score_file_overlap(
    request_values: list[str],
    topic_values: list[str],
    matched_signals: list[str],
    reasoning: list[str],
) -> float:
    score = 0.0

    exact_hits = _match_values(request_values, topic_values)
    if exact_hits:
        matched_signals.extend(exact_hits)
        reasoning.append(f"files overlap: {', '.join(exact_hits[:3])}")
        score += min(6.0, len(exact_hits) * 3.0)

    directory_hits = _match_related_directories(request_values, topic_values)
    if directory_hits:
        matched_signals.extend(directory_hits)
        reasoning.append(f"directory overlap: {', '.join(directory_hits[:3])}")
        score += min(3.0, len(directory_hits) * 1.5)

    basename_hits = _match_related_basenames(request_values, topic_values)
    if basename_hits:
        matched_signals.extend(basename_hits)
        reasoning.append(f"file basename overlap: {', '.join(basename_hits[:3])}")
        score += min(2.0, len(basename_hits) * 1.0)

    return score


def _score_context_overlap(
    request_contexts: list[str],
    topic: TopicPublic,
    matched_signals: list[str],
    reasoning: list[str],
) -> float:
    if not request_contexts:
        return 0.0

    topic_candidates = _topic_text_candidates(topic)
    best_hit: str | None = None
    best_ratio = 0.0
    for context in request_contexts[:8]:
        normalized_context = _normalize_for_match(context)
        if not normalized_context:
            continue
        for candidate in topic_candidates:
            normalized_candidate = _normalize_for_match(candidate)
            if not normalized_candidate:
                continue
            ratio = SequenceMatcher(None, normalized_context, normalized_candidate).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_hit = context

    if best_hit is None:
        return 0.0
    if best_ratio >= 0.82:
        matched_signals.append(best_hit)
        reasoning.append(f"context similarity: {best_ratio:.2f}")
        return 2.5
    if best_ratio >= 0.68:
        matched_signals.append(best_hit)
        reasoning.append(f"context similarity: {best_ratio:.2f}")
        return 1.5
    return 0.0


def _score_case_for_request(case: CasePublic, request: ContextPackBuildRequest) -> float:
    score = 0.0
    score += _simple_file_relevance_score(case.files, request.files)
    score += len(_match_values(case.symbols, request.symbols)) * 2.0
    score += len(_match_values(case.errors, request.errors)) * 2.0
    score += len(_match_values(case.symptoms, request.symptoms)) * 2.0
    case_tokens = set(
        _tokens(" ".join([case.title, case.summary_current or "", case.input_summary or "", *case.files]))
    )
    request_tokens = set(_tokens(_request_search_text(request)))
    score += min(3.0, float(len(case_tokens & request_tokens)))
    return score


def _build_relevant_case_summary(
    case: CasePublic,
    request: ContextPackBuildRequest,
    topic_title: str,
) -> RelevantCaseSummary:
    reasons: list[str] = []
    file_hits = _match_values(case.files, request.files)
    symbol_hits = _match_values(case.symbols, request.symbols)
    error_hits = _match_values(case.errors, request.errors)
    symptom_hits = _match_values(case.symptoms, request.symptoms)
    text_hits = sorted(
        set(_tokens(case.title + " " + (case.summary_current or "") + " " + (case.input_summary or "")))
        & set(_tokens(" ".join(part for part in [request.title, request.request_summary] if part)))
    )

    if file_hits:
        reasons.append(f"file overlap: {', '.join(file_hits[:2])}")
    if symbol_hits:
        reasons.append(f"symbol overlap: {', '.join(symbol_hits[:2])}")
    if error_hits:
        reasons.append(f"error overlap: {', '.join(error_hits[:2])}")
    if symptom_hits:
        reasons.append(f"symptom overlap: {', '.join(symptom_hits[:2])}")
    if text_hits:
        reasons.append(f"request-text overlap: {', '.join(text_hits[:2])}")
    if not reasons:
        reasons.append(f"representative case under topic '{topic_title}'")

    summary = case.summary_current or case.input_summary or case.outcome
    key_commands = [command.cmd for command in case.commands if command.cmd][:3]
    return RelevantCaseSummary(
        case_id=case.id,
        title=case.title,
        short_summary=summary,
        outcome=case.outcome,
        key_files=case.files[:3],
        key_symbols=case.symbols[:3],
        key_errors=case.errors[:3],
        key_commands=key_commands,
        why_selected="; ".join(reasons[:3]),
    )


def _dedupe_relevant_cases(cases: list[RelevantCaseSummary]) -> list[RelevantCaseSummary]:
    seen: set[uuid.UUID] = set()
    deduped: list[RelevantCaseSummary] = []
    for case in cases:
        if case.case_id in seen:
            continue
        seen.add(case.case_id)
        deduped.append(case)
    return deduped


def _score_text_similarity(
    request_fragments: list[str],
    topic: TopicPublic,
    reasoning: list[str],
) -> float:
    normalized_fragments = [
        normalized for fragment in request_fragments if (normalized := _normalize_for_match(fragment))
    ]
    if not normalized_fragments:
        return 0.0

    best_ratio = 0.0
    for normalized_request in normalized_fragments[:10]:
        for candidate in _topic_text_candidates(topic):
            normalized_candidate = _normalize_for_match(candidate)
            if not normalized_candidate:
                continue
            best_ratio = max(
                best_ratio,
                SequenceMatcher(None, normalized_request, normalized_candidate).ratio(),
            )

    if best_ratio >= 0.82:
        reasoning.append(f"request-text similarity: {best_ratio:.2f}")
        return 3.5
    if best_ratio >= 0.68:
        reasoning.append(f"request-text similarity: {best_ratio:.2f}")
        return 2.0
    if best_ratio >= 0.54:
        reasoning.append(f"request-text similarity: {best_ratio:.2f}")
        return 1.0
    return 0.0


def _request_text_fragments(request: TopicMatchRequest | ContextPackBuildRequest) -> list[str]:
    return _dedupe_preserve_order(
        [
            request.title,
            request.request_summary,
            *request.aliases,
            *request.symbols,
            *request.errors,
            *request.symptoms,
            *request.contexts,
        ]
    )


def _request_search_text(request: TopicMatchRequest | ContextPackBuildRequest) -> str:
    file_hints = [hint for path in request.files for hint in _path_hint_tokens(path)]
    values = [
        *_request_text_fragments(request),
        *request.files,
        *file_hints,
    ]
    return " ".join(values)


def _topic_text_candidates(topic: TopicPublic) -> list[str]:
    return _dedupe_preserve_order(
        [
            topic.title,
            topic.workflow_key,
            topic.description or "",
            topic.rollup_summary or "",
            *topic.aliases,
            *topic.vocabulary,
            *topic.canonical_files,
            *topic.canonical_symbols,
            *topic.canonical_errors,
            *topic.canonical_symptoms,
        ]
    )


def _topic_file_hint_tokens(topic: TopicPublic) -> list[str]:
    return [hint for path in topic.canonical_files for hint in _path_hint_tokens(path)]


def _simple_file_relevance_score(case_files: list[str], request_files: list[str]) -> float:
    return _score_file_overlap(case_files, request_files, [], [])


def _match_related_directories(request_values: list[str], topic_values: list[str]) -> list[str]:
    topic_directories = {
        directory
        for value in topic_values
        for directory in _path_directories(value)
        if len(directory) > 2
    }
    hits: list[str] = []
    seen: set[str] = set()
    for value in request_values:
        for directory in reversed(_path_directories(value)):
            if directory in seen:
                continue
            if directory in topic_directories:
                seen.add(directory)
                hits.append(directory)
                break
    return hits


def _match_related_basenames(request_values: list[str], topic_values: list[str]) -> list[str]:
    topic_basenames = {
        basename
        for value in topic_values
        if (basename := _path_basename(value)) is not None
    }
    hits: list[str] = []
    seen: set[str] = set()
    for value in request_values:
        basename = _path_basename(value)
        if basename is None or basename in seen or basename not in topic_basenames:
            continue
        seen.add(basename)
        hits.append(basename)
    return hits


def _path_directories(value: str) -> list[str]:
    normalized = _normalize_path(value)
    if not normalized or "/" not in normalized:
        return []
    parts = [part for part in normalized.split("/") if part]
    return ["/".join(parts[:index]) for index in range(1, len(parts))]


def _path_basename(value: str) -> str | None:
    normalized = _normalize_path(value)
    if not normalized:
        return None
    return normalized.split("/")[-1]


def _path_hint_tokens(value: str) -> list[str]:
    normalized = _normalize_path(value)
    if not normalized:
        return []
    tokens = [token for token in re.split(r"[/.]", normalized) if len(token) > 2]
    return tokens[:12]


def _normalize_path(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().replace("\\", "/")
    normalized = re.sub(r"/+", "/", normalized)
    normalized = re.sub(r"(^|/)\./", r"\1", normalized)
    return normalized.strip("/").lower()


def _match_values(request_values: list[str], topic_values: list[str]) -> list[str]:
    topic_index = {
        normalized: value
        for value in topic_values
        if (normalized := _normalize_for_match(value))
    }
    hits: list[str] = []
    seen: set[str] = set()
    for value in request_values:
        normalized = _normalize_for_match(value)
        if not normalized or normalized in seen or normalized not in topic_index:
            continue
        seen.add(normalized)
        hits.append(value)
    return hits


def _normalize_for_match(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())


def _coerce_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _representative_case_key(case: CasePublic) -> tuple[int, datetime]:
    richness = (
        len(case.files)
        + len(case.symbols)
        + len(case.errors)
        + len(case.symptoms)
        + len(case.commands)
        + len(case.hypotheses)
        + len(case.changes)
    )
    updated_at = case.updated_at or case.opened_at or datetime.min.replace(tzinfo=timezone.utc)
    return (richness, updated_at)


def _tokens_from_case(case: CasePublic) -> list[str]:
    values = [
        case.title,
        case.summary_current or "",
        case.input_summary or "",
        *case.files,
        *case.symbols,
        *case.errors,
        *case.symptoms,
    ]
    return _tokens(" ".join(values))


def _tokens(value: str) -> list[str]:
    tokens = [token for token in TOKEN_RE.findall(value.lower()) if len(token) > 2]
    return tokens[:50]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "topic"


def _top_keys(counter: Counter[str], *, limit: int = 10) -> list[str]:
    return [item for item, _count in counter.most_common(limit)]


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (_clean_optional_string(entry) for entry in value) if item]


def _uuid_list(value: Any) -> list[uuid.UUID]:
    values = _string_list(value)
    parsed: list[uuid.UUID] = []
    for item in values:
        try:
            parsed.append(uuid.UUID(item))
        except ValueError:
            continue
    return parsed


def _clean_optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _canonical_topic_aliases(values: list[str], topic: Topic) -> list[str]:
    # Keep aliases grounded in topic content, not identity handles like workflow_key/title.
    excluded = {
        _normalize_for_match(topic.workflow_key),
        _normalize_for_match(topic.title),
    }
    canonical: list[str] = []
    for value in _dedupe_preserve_order(values):
        normalized = _normalize_for_match(value)
        if not normalized or normalized in excluded:
            continue
        canonical.append(value)
    return canonical


def _dedupe_preserve_order(values: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    deduped: list[Any] = []
    for value in values:
        if value in {None, ""} or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _confidence_for_score(score: float) -> str:
    if score >= 7.0:
        return "high"
    if score >= 3.5:
        return "medium"
    return "low"


def _topic_exists_with_workflow_key(session: Session, workflow_key: str) -> bool:
    statement = select(Topic.id).where(Topic.workflow_key == workflow_key).limit(1)
    return session.exec(statement).first() is not None


def _topic_exists_with_slug(session: Session, slug: str) -> bool:
    statement = select(Topic.id).where(Topic.slug == slug).limit(1)
    return session.exec(statement).first() is not None


def _topic_rollup_needs_refresh(session: Session, topic: Topic) -> bool:
    rollup_payload = _json_object(topic.rollup_data)
    if not rollup_payload:
        return True

    rollup_case_count = rollup_payload.get("case_count")
    if rollup_case_count == 0:
        statement = select(CaseRecord.id).where(CaseRecord.topic_id == topic.id).limit(1)
        return session.exec(statement).first() is not None

    return False
