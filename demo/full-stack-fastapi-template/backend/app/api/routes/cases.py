import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, or_, select

from app.api.deps import CurrentUser, SessionDep
from app.core.cases import (
    apply_case_update,
    build_case_event,
    build_case_event_public,
    build_case_public,
    build_default_case_data,
    render_case_hydration,
    render_case_memo,
)
from app.core.topics import refresh_topic_rollup
from app.models import (
    CaseCreate,
    CaseEvent,
    CaseEventCreate,
    CaseEventPublic,
    CaseEventsPublic,
    CaseHydrationView,
    CaseMemoView,
    CasePublic,
    CaseRecord,
    CasesPublic,
    CaseUpdate,
    Topic,
    get_datetime_utc,
)

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("/", response_model=CasesPublic)
def read_cases(
    session: SessionDep,
    current_user: CurrentUser,
    topic_id: uuid.UUID | None = None,
    status: str | None = None,
    q: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    statement = select(CaseRecord)
    if topic_id is not None:
        statement = statement.where(CaseRecord.topic_id == topic_id)
    if status:
        statement = statement.where(CaseRecord.status == status.strip())
    if q:
        like = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                CaseRecord.title.ilike(like),
                CaseRecord.input_summary.ilike(like),
                CaseRecord.summary_current.ilike(like),
            )
        )

    count = len(session.exec(statement).all())
    statement = statement.order_by(col(CaseRecord.updated_at).desc(), col(CaseRecord.opened_at).desc())
    statement = statement.offset(skip).limit(limit)
    cases = list(session.exec(statement).all())
    topic_ids = {case.topic_id for case in cases}
    topics = {
        topic.id: topic
        for topic in session.exec(select(Topic).where(col(Topic.id).in_(topic_ids))).all()
    } if topic_ids else {}
    return CasesPublic(
        data=[build_case_public(case, topics.get(case.topic_id)) for case in cases],
        count=count,
    )


@router.post("/", response_model=CasePublic, status_code=201)
def create_case(
    session: SessionDep,
    current_user: CurrentUser,
    case_in: CaseCreate,
) -> Any:
    topic = session.get(Topic, case_in.topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    title = (
        (case_in.title or "").strip()
        or (case_in.summary_current or "").strip()
        or (case_in.input_summary or "").strip()
        or f"{topic.title} case"
    )
    now = get_datetime_utc()
    case_record = CaseRecord(
        topic_id=topic.id,
        title=title,
        opened_at=now,
        updated_at=now,
        status=case_in.status.strip() if case_in.status.strip() else "open",
        actor_id=case_in.actor_id,
        source=case_in.source.strip() if isinstance(case_in.source, str) and case_in.source.strip() else None,
        input_summary=(case_in.input_summary.strip() if isinstance(case_in.input_summary, str) and case_in.input_summary.strip() else None),
        summary_current=(case_in.summary_current.strip() if isinstance(case_in.summary_current, str) and case_in.summary_current.strip() else None),
    )
    case_data = build_default_case_data(case_record)
    case_data.update(
        {
            "files": case_in.files,
            "symbols": case_in.symbols,
            "errors": case_in.errors,
            "symptoms": case_in.symptoms,
            "commands": [command.model_dump(mode="json") for command in case_in.commands],
            "hypotheses": [hypothesis.model_dump(mode="json") for hypothesis in case_in.hypotheses],
            "changes": [change.model_dump(mode="json") for change in case_in.changes],
            "outcome": case_in.outcome,
            "next_steps": case_in.next_steps,
        }
    )
    case_record.case_data = case_data
    session.add(case_record)
    session.flush()

    snapshot_payload = (
        case_in.context_pack_snapshot.model_dump(mode="json")
        if case_in.context_pack_snapshot is not None
        else {}
    )
    snapshot_payload.setdefault("topic_id", str(topic.id))
    snapshot_payload.setdefault("case_id", str(case_record.id))
    case_record.context_pack_snapshot = snapshot_payload
    topic.last_used_at = now
    topic.updated_at = now
    session.add(topic)
    session.add(case_record)
    refresh_topic_rollup(session, topic.id, persist=True)
    session.commit()
    session.refresh(case_record)
    session.refresh(topic)
    return build_case_public(case_record, topic)


@router.get("/{case_id}", response_model=CasePublic)
def read_case(session: SessionDep, current_user: CurrentUser, case_id: uuid.UUID) -> Any:
    case_record = session.get(CaseRecord, case_id)
    if case_record is None:
        raise HTTPException(status_code=404, detail="Case not found")
    topic = session.get(Topic, case_record.topic_id)
    return build_case_public(case_record, topic)


@router.patch("/{case_id}", response_model=CasePublic)
def update_case(
    session: SessionDep,
    current_user: CurrentUser,
    case_id: uuid.UUID,
    case_in: CaseUpdate,
) -> Any:
    case_record = session.get(CaseRecord, case_id)
    if case_record is None:
        raise HTTPException(status_code=404, detail="Case not found")
    topic = session.get(Topic, case_record.topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    update = case_in.model_dump(mode="json", exclude_unset=True)
    if not update:
        raise HTTPException(status_code=422, detail="No fields to update")

    apply_case_update(case_record, update)
    topic.last_used_at = get_datetime_utc()
    topic.updated_at = topic.last_used_at
    session.add(case_record)
    session.add(topic)
    refresh_topic_rollup(session, topic.id, persist=True)
    session.commit()
    session.refresh(case_record)
    session.refresh(topic)
    return build_case_public(case_record, topic)


@router.get("/{case_id}/memo", response_model=CaseMemoView)
def read_case_memo(session: SessionDep, current_user: CurrentUser, case_id: uuid.UUID) -> Any:
    case_record = session.get(CaseRecord, case_id)
    if case_record is None:
        raise HTTPException(status_code=404, detail="Case not found")
    topic = session.get(Topic, case_record.topic_id)
    return render_case_memo(build_case_public(case_record, topic))


@router.get("/{case_id}/hydration", response_model=CaseHydrationView)
def read_case_hydration(session: SessionDep, current_user: CurrentUser, case_id: uuid.UUID) -> Any:
    case_record = session.get(CaseRecord, case_id)
    if case_record is None:
        raise HTTPException(status_code=404, detail="Case not found")
    topic = session.get(Topic, case_record.topic_id)
    return render_case_hydration(build_case_public(case_record, topic))


@router.get("/{case_id}/events", response_model=CaseEventsPublic)
def read_case_events(session: SessionDep, current_user: CurrentUser, case_id: uuid.UUID) -> Any:
    case_record = session.get(CaseRecord, case_id)
    if case_record is None:
        raise HTTPException(status_code=404, detail="Case not found")
    statement = (
        select(CaseEvent)
        .where(CaseEvent.case_id == case_id)
        .order_by(col(CaseEvent.ts).asc(), col(CaseEvent.id).asc())
    )
    events = list(session.exec(statement).all())
    return CaseEventsPublic(
        data=[build_case_event_public(event) for event in events],
        count=len(events),
    )


@router.post("/{case_id}/events", response_model=CaseEventPublic, status_code=201)
def create_case_event_route(
    session: SessionDep,
    current_user: CurrentUser,
    case_id: uuid.UUID,
    event_in: CaseEventCreate,
) -> Any:
    case_record = session.get(CaseRecord, case_id)
    if case_record is None:
        raise HTTPException(status_code=404, detail="Case not found")

    case_event = build_case_event(case_id, event_in)
    session.add(case_event)
    session.commit()
    session.refresh(case_event)
    return build_case_event_public(case_event)
