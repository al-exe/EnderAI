import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, SessionDep
from app.core.demo import ensure_demo_workspace
from app.core.skills import (
    build_skill_public,
    build_skill_use_result,
    count_skills,
    create_or_refresh_skill_from_case,
    create_or_refresh_skill_from_topic,
    generate_skill_from_request,
    list_skill_models,
    match_skills,
    read_skill_model,
    record_skill_usage,
)
from app.core.topics import claim_legacy_orphan_topics_for_owner
from app.models import (
    SkillGenerateRequest,
    SkillMatchRequest,
    SkillMatchResult,
    SkillPublic,
    SkillsPublic,
    SkillUseRequest,
    SkillUseResult,
)

router = APIRouter(prefix="/skills", tags=["skills"])


def _owner_scope_id(current_user: CurrentUser) -> uuid.UUID:
    return current_user.id


def _prepare_read_scope(
    session: SessionDep,
    current_user: CurrentUser,
    *,
    demo: bool,
) -> uuid.UUID:
    owner_id = _owner_scope_id(current_user)
    if demo and ensure_demo_workspace(session, current_user):
        session.commit()
        session.refresh(current_user)
    claimed = claim_legacy_orphan_topics_for_owner(session, owner_id)
    if claimed:
        session.commit()
    return owner_id


@router.get("/", response_model=SkillsPublic)
def read_skills(
    session: SessionDep,
    current_user: CurrentUser,
    demo: bool = Query(default=False),
    status: str | None = None,
    source_type: str | None = None,
    q: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    owner_id = _prepare_read_scope(session, current_user, demo=demo)
    skills = list_skill_models(
        session,
        owner_id=owner_id,
        demo=demo,
        status=status,
        source_type=source_type,
        q=q,
        skip=skip,
        limit=limit,
    )
    return SkillsPublic(
        data=[build_skill_public(skill) for skill in skills],
        count=count_skills(
            session,
            owner_id=owner_id,
            demo=demo,
            status=status,
            source_type=source_type,
            q=q,
        ),
    )


@router.post("/generate", response_model=SkillPublic, status_code=201)
def generate_skill(
    session: SessionDep,
    current_user: CurrentUser,
    request: SkillGenerateRequest,
    demo: bool = Query(default=False),
) -> Any:
    owner_id = _owner_scope_id(current_user)
    if demo and ensure_demo_workspace(session, current_user):
        session.commit()
        session.refresh(current_user)
    claimed = claim_legacy_orphan_topics_for_owner(session, owner_id)
    if claimed:
        session.commit()
    try:
        skill = generate_skill_from_request(
            session,
            request,
            owner_id=owner_id,
            demo=demo,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 422 if "exactly one" in detail else 404
        raise HTTPException(status_code=status_code, detail=detail)

    session.commit()
    session.refresh(skill)
    return build_skill_public(skill)


@router.post("/match", response_model=SkillMatchResult)
def match_skills_route(
    session: SessionDep,
    current_user: CurrentUser,
    request: SkillMatchRequest,
    demo: bool = Query(default=False),
) -> Any:
    owner_id = _prepare_read_scope(session, current_user, demo=demo)
    return match_skills(session, request, owner_id=owner_id, demo=demo)


@router.post("/use", response_model=SkillUseResult)
def use_skill(
    session: SessionDep,
    current_user: CurrentUser,
    request: SkillUseRequest,
    demo: bool = Query(default=False),
) -> Any:
    owner_id = _prepare_read_scope(session, current_user, demo=demo)
    try:
        result = build_skill_use_result(
            session,
            request,
            owner_id=owner_id,
            demo=demo,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if result.selected_skill is not None:
        record_skill_usage(session, result.selected_skill.id, owner_id=owner_id)
        session.commit()
        refreshed = read_skill_model(
            session,
            result.selected_skill.id,
            owner_id=owner_id,
            demo=demo,
        )
        if refreshed is not None:
            result.selected_skill = build_skill_public(refreshed)
    return result


@router.get("/{skill_id}", response_model=SkillPublic)
def read_skill(
    session: SessionDep,
    current_user: CurrentUser,
    skill_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> Any:
    owner_id = _prepare_read_scope(session, current_user, demo=demo)
    skill = read_skill_model(session, skill_id, owner_id=owner_id, demo=demo)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return build_skill_public(skill)


@router.post("/{skill_id}/refresh", response_model=SkillPublic)
def refresh_skill(
    session: SessionDep,
    current_user: CurrentUser,
    skill_id: uuid.UUID,
    demo: bool = Query(default=False),
) -> Any:
    owner_id = _owner_scope_id(current_user)
    if demo and ensure_demo_workspace(session, current_user):
        session.commit()
        session.refresh(current_user)
    skill = read_skill_model(session, skill_id, owner_id=owner_id, demo=demo)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.source_type == "case" and skill.source_case_ids:
        refreshed = create_or_refresh_skill_from_case(
            session,
            uuid.UUID(skill.source_case_ids[0]),
            owner_id=owner_id,
            demo=demo,
            title=skill.title,
            status=skill.status,
        )
    elif skill.source_topic_id is not None:
        refreshed = create_or_refresh_skill_from_topic(
            session,
            skill.source_topic_id,
            owner_id=owner_id,
            demo=demo,
            source_type=skill.source_type,  # type: ignore[arg-type]
            title=skill.title,
            status=skill.status,
        )
    else:
        raise HTTPException(status_code=422, detail="Skill has no refreshable source")

    session.commit()
    session.refresh(refreshed)
    return build_skill_public(refreshed)


@router.post("/{skill_id}/use", response_model=SkillUseResult)
def use_skill_by_id(
    session: SessionDep,
    current_user: CurrentUser,
    skill_id: uuid.UUID,
    request: SkillUseRequest | None = None,
    demo: bool = Query(default=False),
) -> Any:
    use_request = request or SkillUseRequest()
    use_request.skill_id = skill_id
    return use_skill(
        session=session,
        current_user=current_user,
        request=use_request,
        demo=demo,
    )
