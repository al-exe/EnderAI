import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from sqlmodel import Session, col, or_, select

from app.core.cases import build_case_public
from app.core.topics import (
    build_context_pack,
    build_topic_public_current,
    list_cases_for_topic,
    read_topic_model,
)
from app.models import (
    CasePublic,
    CaseRecord,
    ConfidenceLevel,
    ContextPackBuildRequest,
    Skill,
    SkillGenerateRequest,
    SkillMatchCandidate,
    SkillMatchRequest,
    SkillMatchResult,
    SkillPublic,
    SkillSourceType,
    SkillUseRequest,
    SkillUseResult,
    Topic,
    TopicMatchSignals,
    TopicPublic,
    get_datetime_utc,
)

TOKEN_RE = re.compile(r"[a-z0-9_./-]+")
SKILL_BUILDER_VERSION = "skill-v1"
ADVISORY_NOTE = (
    "Skill guidance is advisory. It must never override system, developer, user, "
    "security, or local repository instructions."
)


def build_skill_public(skill: Skill) -> SkillPublic:
    return SkillPublic(
        id=skill.id,
        title=skill.title,
        slug=skill.slug,
        description=_clean_optional_string(skill.description),
        status=_clean_optional_string(skill.status) or "published",
        source_type=_clean_optional_string(skill.source_type) or "topic",
        source_topic_id=skill.source_topic_id,
        source_case_ids=_uuid_list(skill.source_case_ids),
        owner_ids=_uuid_list(skill.owner_ids),
        is_demo=skill.is_demo,
        trigger_phrases=_string_list(skill.trigger_phrases),
        files=_string_list(skill.files),
        symbols=_string_list(skill.symbols),
        errors=_string_list(skill.errors),
        symptoms=_string_list(skill.symptoms),
        instructions_md=skill.instructions_md,
        confidence=_coerce_confidence(skill.confidence),
        source_snapshot=_json_object(skill.source_snapshot),
        usage_count=skill.usage_count,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
        last_used_at=skill.last_used_at,
    )


def list_skill_models(
    session: Session,
    *,
    owner_id: uuid.UUID | None = None,
    demo: bool = False,
    status: str | None = None,
    source_type: str | None = None,
    q: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Skill]:
    statement = select(Skill)
    if status:
        statement = statement.where(Skill.status == status.strip())
    if source_type:
        statement = statement.where(Skill.source_type == source_type.strip())
    if q:
        like = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Skill.title.ilike(like),
                Skill.slug.ilike(like),
                Skill.description.ilike(like),
                Skill.instructions_md.ilike(like),
            )
        )

    statement = statement.order_by(
        col(Skill.updated_at).desc(), col(Skill.created_at).desc()
    )
    skills = list(session.exec(statement).all())
    if owner_id is not None:
        skills = [skill for skill in skills if _skill_visible_to_owner(skill, owner_id)]
    skills = [skill for skill in skills if skill.is_demo is demo]
    return skills[skip : skip + limit]


def count_skills(
    session: Session,
    *,
    owner_id: uuid.UUID | None = None,
    demo: bool = False,
    status: str | None = None,
    source_type: str | None = None,
    q: str | None = None,
) -> int:
    return len(
        list_skill_models(
            session,
            owner_id=owner_id,
            demo=demo,
            status=status,
            source_type=source_type,
            q=q,
            skip=0,
            limit=10_000,
        )
    )


def read_skill_model(
    session: Session,
    skill_id: uuid.UUID,
    *,
    owner_id: uuid.UUID | None = None,
    demo: bool = False,
) -> Skill | None:
    skill = session.get(Skill, skill_id)
    if skill is None:
        return None
    if skill.is_demo is not demo:
        return None
    if owner_id is not None and not _skill_visible_to_owner(skill, owner_id):
        return None
    return skill


def generate_skill_from_request(
    session: Session,
    request: SkillGenerateRequest,
    *,
    owner_id: uuid.UUID,
    demo: bool = False,
) -> Skill:
    source_count = sum(
        1
        for value in [request.topic_id, request.case_id, request.context_pack]
        if value is not None
    )
    if source_count != 1:
        raise ValueError("Provide exactly one of topic_id, case_id, or context_pack")

    if request.topic_id is not None:
        return create_or_refresh_skill_from_topic(
            session,
            request.topic_id,
            owner_id=owner_id,
            demo=demo,
            source_type="topic",
            title=request.title,
            status=request.status,
        )

    if request.case_id is not None:
        return create_or_refresh_skill_from_case(
            session,
            request.case_id,
            owner_id=owner_id,
            demo=demo,
            title=request.title,
            status=request.status,
        )

    context_pack = build_context_pack(
        session,
        request.context_pack or ContextPackBuildRequest(),
        owner_id=owner_id,
        demo=demo,
    )
    topic_id = context_pack.context_pack_snapshot.topic_id
    if topic_id is None:
        raise ValueError("ContextPack did not select a Topic")

    return create_or_refresh_skill_from_topic(
        session,
        topic_id,
        owner_id=owner_id,
        demo=demo,
        source_type="context_pack",
        title=request.title,
        status=request.status,
        context_pack_snapshot=context_pack.model_dump(mode="json"),
    )


def create_or_refresh_skill_from_case(
    session: Session,
    case_id: uuid.UUID,
    *,
    owner_id: uuid.UUID,
    demo: bool = False,
    title: str | None = None,
    status: str = "published",
) -> Skill:
    case_record = session.get(CaseRecord, case_id)
    if case_record is None:
        raise ValueError("Case not found")

    topic = read_topic_model(
        session,
        case_record.topic_id,
        owner_id=owner_id,
        demo=demo,
    )
    if topic is None:
        raise ValueError("Case not found")

    case_public = build_case_public(case_record, topic)
    return _create_or_refresh_skill(
        session,
        topic,
        owner_id=owner_id,
        demo=demo,
        source_type="case",
        primary_case=case_public,
        title=title,
        status=status,
    )


def create_or_refresh_skill_from_topic(
    session: Session,
    topic_id: uuid.UUID,
    *,
    owner_id: uuid.UUID,
    demo: bool = False,
    source_type: SkillSourceType = "topic",
    title: str | None = None,
    status: str = "published",
    context_pack_snapshot: dict[str, Any] | None = None,
) -> Skill:
    topic = read_topic_model(session, topic_id, owner_id=owner_id, demo=demo)
    if topic is None:
        raise ValueError("Topic not found")

    return _create_or_refresh_skill(
        session,
        topic,
        owner_id=owner_id,
        demo=demo,
        source_type=source_type,
        title=title,
        status=status,
        context_pack_snapshot=context_pack_snapshot,
    )


def ensure_demo_skills_for_owner(session: Session, owner_id: uuid.UUID) -> int:
    owner_id_str = str(owner_id)
    demo_topics = [
        topic
        for topic in session.exec(select(Topic).where(Topic.is_demo.is_(True))).all()
        if owner_id_str in _string_list(topic.owner_ids)
    ]
    created_or_updated = 0
    for topic in demo_topics:
        existing = _find_existing_skill(
            session,
            owner_id=owner_id,
            demo=True,
            source_type="demo",
            topic_id=topic.id,
        )
        if existing is not None:
            continue
        create_or_refresh_skill_from_topic(
            session,
            topic.id,
            owner_id=owner_id,
            demo=True,
            source_type="demo",
            status="published",
        )
        created_or_updated += 1
    return created_or_updated


def match_skills(
    session: Session,
    request: SkillMatchRequest,
    *,
    owner_id: uuid.UUID,
    demo: bool = False,
) -> SkillMatchResult:
    skills = [
        build_skill_public(skill)
        for skill in list_skill_models(
            session,
            owner_id=owner_id,
            demo=demo,
            status="published",
        )
    ]
    candidates = [_score_skill_match(skill, request) for skill in skills]
    candidates = [candidate for candidate in candidates if candidate.score > 0]
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return SkillMatchResult(candidates=candidates[: max(request.limit, 1)])


def build_skill_use_result(
    session: Session,
    request: SkillUseRequest,
    *,
    owner_id: uuid.UUID,
    demo: bool = False,
) -> SkillUseResult:
    signals = _use_request_with_case_signals(
        session, request, owner_id=owner_id, demo=demo
    )
    if request.skill_id is not None:
        skill = read_skill_model(
            session, request.skill_id, owner_id=owner_id, demo=demo
        )
        if skill is None:
            raise ValueError("Skill not found")
        public = build_skill_public(skill)
        candidate = SkillMatchCandidate(
            skill=public,
            score=100.0,
            confidence="high",
            matched_signals=[],
            reasoning=["skill_id explicitly selected"],
        )
        return _build_use_result(public, [candidate])

    match_result = match_skills(
        session,
        SkillMatchRequest(
            title=signals.title,
            request_summary=signals.request_summary,
            aliases=signals.aliases,
            files=signals.files,
            symbols=signals.symbols,
            errors=signals.errors,
            symptoms=signals.symptoms,
            contexts=signals.contexts,
            limit=request.max_skills,
        ),
        owner_id=owner_id,
        demo=demo,
    )
    selected = match_result.candidates[0].skill if match_result.candidates else None
    return _build_use_result(selected, match_result.candidates)


def record_skill_usage(
    session: Session, skill_id: uuid.UUID, *, owner_id: uuid.UUID
) -> None:
    skill = session.get(Skill, skill_id)
    if skill is None or not _skill_visible_to_owner(skill, owner_id):
        return
    now = get_datetime_utc()
    skill.usage_count += 1
    skill.last_used_at = now
    skill.updated_at = now
    session.add(skill)


def _create_or_refresh_skill(
    session: Session,
    topic: Topic,
    *,
    owner_id: uuid.UUID,
    demo: bool,
    source_type: SkillSourceType,
    title: str | None = None,
    status: str = "published",
    primary_case: CasePublic | None = None,
    context_pack_snapshot: dict[str, Any] | None = None,
) -> Skill:
    topic_public = build_topic_public_current(
        session,
        topic,
        owner_id=owner_id,
        demo=demo,
    )
    cases = list_cases_for_topic(session, topic.id, owner_id=owner_id, demo=demo)
    if primary_case is not None:
        cases = [primary_case, *[case for case in cases if case.id != primary_case.id]]

    skill_title = _clean_optional_string(title) or _default_skill_title(topic_public)
    source_case_ids = _select_source_case_ids(topic_public, cases, primary_case)
    instructions_md = _render_skill_instructions(
        title=skill_title,
        topic=topic_public,
        cases=cases,
        primary_case=primary_case,
        source_type=source_type,
        context_pack_snapshot=context_pack_snapshot,
    )
    source_snapshot = _build_source_snapshot(
        topic=topic_public,
        cases=cases,
        primary_case=primary_case,
        source_type=source_type,
        context_pack_snapshot=context_pack_snapshot,
    )
    now = get_datetime_utc()
    existing = _find_existing_skill(
        session,
        owner_id=owner_id,
        demo=demo,
        source_type=source_type,
        topic_id=topic.id,
        case_ids=source_case_ids if source_type == "case" else None,
    )
    skill = existing or Skill(
        title=skill_title,
        slug=_skill_slug(skill_title, owner_id, topic.id, source_type),
        source_type=source_type,
        source_topic_id=topic.id,
        owner_ids=[str(owner_id)],
        is_demo=demo,
        created_at=now,
    )
    skill.title = skill_title
    skill.slug = _skill_slug(skill_title, owner_id, topic.id, source_type)
    skill.description = _skill_description(topic_public, primary_case)
    skill.status = status
    skill.source_type = source_type
    skill.source_topic_id = topic.id
    skill.source_case_ids = source_case_ids
    skill.owner_ids = _dedupe_preserve_order([*skill.owner_ids, str(owner_id)])
    skill.is_demo = demo
    skill.trigger_phrases = _build_trigger_phrases(topic_public, primary_case)
    skill.files = topic_public.canonical_files[:12]
    skill.symbols = topic_public.canonical_symbols[:12]
    skill.errors = topic_public.canonical_errors[:12]
    skill.symptoms = topic_public.canonical_symptoms[:12]
    skill.instructions_md = instructions_md
    skill.confidence = _skill_confidence(topic_public, cases)
    skill.source_snapshot = source_snapshot
    skill.updated_at = now
    session.add(skill)
    session.flush()
    return skill


def _find_existing_skill(
    session: Session,
    *,
    owner_id: uuid.UUID,
    demo: bool,
    source_type: str,
    topic_id: uuid.UUID,
    case_ids: list[str] | None = None,
) -> Skill | None:
    rows = list(
        session.exec(
            select(Skill)
            .where(Skill.source_topic_id == topic_id)
            .where(Skill.source_type == source_type)
            .where(Skill.is_demo == demo)
        ).all()
    )
    for row in rows:
        if not _skill_visible_to_owner(row, owner_id):
            continue
        if case_ids is not None and not set(case_ids).issubset(
            set(row.source_case_ids)
        ):
            continue
        return row
    return None


def _use_request_with_case_signals(
    session: Session,
    request: SkillUseRequest,
    *,
    owner_id: uuid.UUID,
    demo: bool,
) -> SkillUseRequest:
    if request.case_id is None:
        return request

    case_record = session.get(CaseRecord, request.case_id)
    if case_record is None:
        raise ValueError("Case not found")
    topic = read_topic_model(
        session,
        case_record.topic_id,
        owner_id=owner_id,
        demo=demo,
    )
    if topic is None:
        raise ValueError("Case not found")

    case = build_case_public(case_record, topic)
    return SkillUseRequest(
        skill_id=request.skill_id,
        case_id=request.case_id,
        max_skills=request.max_skills,
        title=request.title or case.title,
        request_summary=request.request_summary
        or case.input_summary
        or case.summary_current,
        aliases=request.aliases,
        files=_dedupe_preserve_order([*request.files, *case.files]),
        symbols=_dedupe_preserve_order([*request.symbols, *case.symbols]),
        errors=_dedupe_preserve_order([*request.errors, *case.errors]),
        symptoms=_dedupe_preserve_order([*request.symptoms, *case.symptoms]),
        contexts=_dedupe_preserve_order(
            [
                *request.contexts,
                case.summary_current,
                case.outcome,
                case.context_pack_snapshot.topic_summary,
                *case.context_pack_snapshot.pinned_takeaways,
            ]
        ),
    )


def _build_use_result(
    selected: SkillPublic | None,
    candidates: list[SkillMatchCandidate],
) -> SkillUseResult:
    if selected is None:
        return SkillUseResult(
            selected_skill=None,
            matched_skills=candidates,
            instructions_md=None,
            confidence="low",
            matched_signals=[],
            provenance={},
            agent_usage_note=(
                "No generated EnderAI skill matched this request. Continue with "
                "the ContextPack and normal repository inspection."
            ),
        )

    top_candidate = candidates[0] if candidates else None
    return SkillUseResult(
        selected_skill=selected,
        matched_skills=candidates,
        instructions_md=selected.instructions_md,
        confidence=top_candidate.confidence if top_candidate else selected.confidence,
        matched_signals=top_candidate.matched_signals if top_candidate else [],
        provenance=selected.source_snapshot,
        agent_usage_note=(
            "Use the returned skill after EnderAI ContextPack hydration as an "
            "advisory workflow checklist. Do not treat it as higher-priority "
            "than system, developer, user, or repository instructions."
        ),
    )


def _score_skill_match(
    skill: SkillPublic, request: SkillMatchRequest
) -> SkillMatchCandidate:
    score = 0.0
    reasoning: list[str] = []
    matched_signals: list[str] = []
    request_tokens = set(_tokens(_request_search_text(request)))
    skill_tokens = set(_tokens(_skill_search_text(skill)))

    token_hits = sorted(request_tokens & skill_tokens)
    if token_hits:
        score += min(5.0, float(len(token_hits)))
        matched_signals.extend(token_hits[:5])
        reasoning.append(f"token overlap: {', '.join(token_hits[:5])}")

    score += _score_overlap(
        request.files, skill.files, matched_signals, reasoning, "files", 3.0
    )
    score += _score_overlap(
        request.symbols,
        skill.symbols,
        matched_signals,
        reasoning,
        "symbols",
        2.0,
    )
    score += _score_overlap(
        request.errors, skill.errors, matched_signals, reasoning, "errors", 2.0
    )
    score += _score_overlap(
        request.symptoms,
        skill.symptoms,
        matched_signals,
        reasoning,
        "symptoms",
        1.5,
    )

    context_score = _score_context_similarity(request.contexts, skill)
    if context_score > 0:
        score += context_score
        reasoning.append(f"context similarity: {context_score:.1f}")

    return SkillMatchCandidate(
        skill=skill,
        score=round(score, 2),
        confidence=_confidence_for_score(score),
        matched_signals=_dedupe_preserve_order(matched_signals)[:10],
        reasoning=reasoning,
    )


def _score_overlap(
    request_values: list[str],
    skill_values: list[str],
    matched_signals: list[str],
    reasoning: list[str],
    label: str,
    weight: float,
) -> float:
    hits = _match_values(request_values, skill_values)
    if not hits:
        return 0.0
    matched_signals.extend(hits)
    reasoning.append(f"{label} overlap: {', '.join(hits[:3])}")
    return min(weight * 3.0, len(hits) * weight)


def _score_context_similarity(request_contexts: list[str], skill: SkillPublic) -> float:
    if not request_contexts:
        return 0.0
    candidates = [
        skill.title,
        skill.description or "",
        *skill.trigger_phrases,
        *_string_list(skill.source_snapshot.get("pinned_takeaways")),
    ]
    best_ratio = 0.0
    for context in request_contexts[:6]:
        normalized_context = _normalize_for_match(context)
        if not normalized_context:
            continue
        for candidate in candidates:
            normalized_candidate = _normalize_for_match(str(candidate))
            if not normalized_candidate:
                continue
            best_ratio = max(
                best_ratio,
                SequenceMatcher(None, normalized_context, normalized_candidate).ratio(),
            )
    if best_ratio >= 0.82:
        return 3.0
    if best_ratio >= 0.68:
        return 2.0
    if best_ratio >= 0.54:
        return 1.0
    return 0.0


def _render_skill_instructions(
    *,
    title: str,
    topic: TopicPublic,
    cases: list[CasePublic],
    primary_case: CasePublic | None,
    source_type: str,
    context_pack_snapshot: dict[str, Any] | None,
) -> str:
    takeaways = _dedupe_preserve_order(
        [
            *topic.pinned_takeaways,
            *[case.outcome for case in cases if case.outcome],
        ]
    )[:8]
    open_questions = _dedupe_preserve_order(topic.open_questions)[:6]
    negative_history = _dedupe_preserve_order(topic.negative_history)[:6]
    relevant_cases = _compact_cases(cases)
    trigger_phrases = _build_trigger_phrases(topic, primary_case)
    source_label = {
        "case": "a prior Case",
        "context_pack": "a ContextPack",
        "demo": "demo Topics and Cases",
        "manual": "manual input",
        "topic": "a Topic rollup",
    }.get(source_type, "EnderAI context")
    context_pack_line = (
        "\n- ContextPack source: selected by live request signals."
        if context_pack_snapshot
        else ""
    )

    sections = [
        f"# Skill: {title}",
        ADVISORY_NOTE,
        "## When To Use",
        _bullet_block(
            trigger_phrases[:8],
            fallback=f"Use when the work resembles {topic.title}.",
        ),
        "## Workflow",
        _numbered_block(
            [
                "Confirm the current request matches the triggers before applying this skill.",
                "Read the EnderAI ContextPack first, then use this skill as a checklist.",
                "Inspect the canonical files and symbols before editing.",
                "Reuse the prior successful approach when symptoms/errors match.",
                "Check negative history and open questions before assuming the old fix still applies.",
                "Record material findings with enderai_update_case and close with enderai_finish_case.",
            ]
        ),
        "## Canonical Signals",
        "\n".join(
            [
                f"- Files: {_inline_list(topic.canonical_files)}",
                f"- Symbols: {_inline_list(topic.canonical_symbols)}",
                f"- Errors: {_inline_list(topic.canonical_errors)}",
                f"- Symptoms: {_inline_list(topic.canonical_symptoms)}",
            ]
        ),
        "## Prior Outcomes To Reuse",
        _bullet_block(takeaways, fallback="No prior outcomes were promoted yet."),
        "## Prior Cases",
        _bullet_block(
            relevant_cases, fallback="No representative cases were available."
        ),
        "## Checks And Guardrails",
        _bullet_block(
            [
                *[f"Open question: {question}" for question in open_questions],
                *[f"Do not repeat: {item}" for item in negative_history],
                ADVISORY_NOTE,
            ],
            fallback=ADVISORY_NOTE,
        ),
        "## Provenance",
        "\n".join(
            [
                f"- Generated from {source_label}.",
                f"- Topic: {topic.title} ({topic.workflow_key}).",
                f"- Builder: {SKILL_BUILDER_VERSION}.",
                context_pack_line,
            ]
        ).strip(),
    ]
    return "\n\n".join(section for section in sections if section.strip())


def _build_source_snapshot(
    *,
    topic: TopicPublic,
    cases: list[CasePublic],
    primary_case: CasePublic | None,
    source_type: str,
    context_pack_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "builder_version": SKILL_BUILDER_VERSION,
        "source_type": source_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic": {
            "id": str(topic.id),
            "title": topic.title,
            "workflow_key": topic.workflow_key,
            "summary": topic.rollup_summary,
            "case_count": topic.case_count,
        },
        "primary_case_id": str(primary_case.id) if primary_case else None,
        "source_case_ids": _select_source_case_ids(topic, cases, primary_case),
        "canonical_files": topic.canonical_files,
        "canonical_symbols": topic.canonical_symbols,
        "canonical_errors": topic.canonical_errors,
        "canonical_symptoms": topic.canonical_symptoms,
        "trigger_phrases": _build_trigger_phrases(topic, primary_case),
        "pinned_takeaways": topic.pinned_takeaways,
        "open_questions": topic.open_questions,
        "negative_history": topic.negative_history,
        "cases": [
            {
                "id": str(case.id),
                "title": case.title,
                "summary": case.summary_current or case.input_summary,
                "outcome": case.outcome,
            }
            for case in cases[:6]
        ],
        "context_pack": context_pack_snapshot,
    }


def _select_source_case_ids(
    topic: TopicPublic,
    cases: list[CasePublic],
    primary_case: CasePublic | None,
) -> list[str]:
    ids: list[uuid.UUID] = []
    if primary_case is not None:
        ids.append(primary_case.id)
    ids.extend(topic.representative_case_ids)
    ids.extend(topic.recent_case_ids)
    ids.extend(case.id for case in cases[:6])
    return [str(case_id) for case_id in _dedupe_preserve_order(ids)[:8]]


def _compact_cases(cases: list[CasePublic]) -> list[str]:
    compact: list[str] = []
    for case in cases[:5]:
        summary = case.summary_current or case.input_summary or case.outcome
        if summary:
            compact.append(f"{case.title}: {summary}")
        else:
            compact.append(case.title)
    return compact


def _build_trigger_phrases(
    topic: TopicPublic,
    primary_case: CasePublic | None = None,
) -> list[str]:
    values = [
        topic.title,
        topic.workflow_key,
        topic.rollup_summary,
        *topic.aliases,
        *topic.vocabulary[:8],
        *topic.canonical_errors[:4],
        *topic.canonical_symptoms[:4],
    ]
    if primary_case is not None:
        values.extend(
            [
                primary_case.title,
                primary_case.input_summary,
                primary_case.summary_current,
                *primary_case.errors[:3],
                *primary_case.symptoms[:3],
            ]
        )
    return _dedupe_preserve_order(values)[:20]


def _skill_description(topic: TopicPublic, primary_case: CasePublic | None) -> str:
    if primary_case is not None:
        return f"Reusable workflow generated from case '{primary_case.title}' under {topic.title}."
    return f"Reusable workflow generated from EnderAI Topic '{topic.title}'."


def _default_skill_title(topic: TopicPublic) -> str:
    return f"{topic.title} Workflow Skill"


def _skill_slug(
    title: str,
    owner_id: uuid.UUID,
    topic_id: uuid.UUID,
    source_type: str,
) -> str:
    return "-".join(
        [
            _slugify(title),
            source_type.replace("_", "-"),
            owner_id.hex[:8],
            topic_id.hex[:8],
        ]
    )[:255]


def _skill_confidence(topic: TopicPublic, cases: list[CasePublic]) -> ConfidenceLevel:
    if topic.case_count >= 3 or len(cases) >= 3:
        return "high"
    if topic.case_count >= 1 or cases:
        return "medium"
    return "low"


def _skill_visible_to_owner(skill: Skill, owner_id: uuid.UUID) -> bool:
    return str(owner_id) in _string_list(skill.owner_ids)


def _request_search_text(request: TopicMatchSignals) -> str:
    return " ".join(
        [
            request.title or "",
            request.request_summary or "",
            *request.aliases,
            *request.files,
            *request.symbols,
            *request.errors,
            *request.symptoms,
            *request.contexts,
        ]
    )


def _skill_search_text(skill: SkillPublic) -> str:
    return " ".join(
        [
            skill.title,
            skill.slug,
            skill.description or "",
            *skill.trigger_phrases,
            *skill.files,
            *skill.symbols,
            *skill.errors,
            *skill.symptoms,
            skill.instructions_md,
        ]
    )


def _match_values(request_values: list[str], skill_values: list[str]) -> list[str]:
    skill_index = {
        normalized: value
        for value in skill_values
        if (normalized := _normalize_for_match(value))
    }
    hits: list[str] = []
    seen: set[str] = set()
    for request_value in request_values:
        normalized = _normalize_for_match(request_value)
        if not normalized or normalized in seen:
            continue
        if normalized in skill_index:
            seen.add(normalized)
            hits.append(skill_index[normalized])
            continue
        for skill_normalized, skill_value in skill_index.items():
            if normalized in skill_normalized or skill_normalized in normalized:
                seen.add(normalized)
                hits.append(skill_value)
                break
    return hits


def _confidence_for_score(score: float) -> ConfidenceLevel:
    if score >= 7.0:
        return "high"
    if score >= 3.0:
        return "medium"
    return "low"


def _coerce_confidence(value: str | None) -> ConfidenceLevel:
    normalized = (value or "").strip().lower()
    if normalized in {"high", "medium", "low"}:
        return normalized  # type: ignore[return-value]
    return "low"


def _bullet_block(items: list[str], *, fallback: str) -> str:
    clean_items = _dedupe_preserve_order(items)
    if not clean_items:
        return f"- {fallback}"
    return "\n".join(f"- {item}" for item in clean_items)


def _numbered_block(items: list[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def _inline_list(items: list[str], limit: int = 8) -> str:
    clean_items = _dedupe_preserve_order(items)[:limit]
    return ", ".join(clean_items) if clean_items else "None captured"


def _tokens(value: str) -> list[str]:
    return [
        match.group(0) for match in TOKEN_RE.finditer(value.lower()) if match.group(0)
    ]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "skill"


def _normalize_for_match(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())


def _clean_optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _json_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _uuid_list(value: Any) -> list[uuid.UUID]:
    uuids: list[uuid.UUID] = []
    for item in _string_list(value):
        try:
            uuids.append(uuid.UUID(item))
        except ValueError:
            continue
    return uuids


def _dedupe_preserve_order(values: list[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        key = str(value).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out
