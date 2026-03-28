import uuid
from typing import Any

from app.models import (
    CaseEvent,
    CaseEventCreate,
    CaseEventPublic,
    CaseHydrationSignals,
    CaseHydrationView,
    CaseMemoView,
    CasePublic,
    CaseRecord,
    ChangeRecord,
    CommandRecord,
    ContextPackSnapshot,
    HypothesisRecord,
    Topic,
    get_datetime_utc,
)

CASE_DATA_FIELDS = {
    "files",
    "symbols",
    "errors",
    "symptoms",
    "commands",
    "hypotheses",
    "changes",
    "outcome",
    "next_steps",
}

TERMINAL_CASE_STATUSES = {
    "aborted",
    "cancelled",
    "canceled",
    "closed",
    "complete",
    "completed",
    "done",
    "failed",
    "resolved",
}


def build_case_public(case_record: CaseRecord, topic: Topic | None) -> CasePublic:
    case_data = build_default_case_data(case_record)
    case_data.update(_normalized_case_data(case_record.case_data))

    summary_current = _clean_optional_string(case_record.summary_current)

    title = _clean_optional_string(case_record.title)
    if title is None:
        title = summary_current or (topic.title if topic else "Case")

    snapshot = normalize_context_pack_snapshot(
        case_record.context_pack_snapshot,
        topic_id=case_record.topic_id,
        case_id=case_record.id,
    )

    return CasePublic(
        id=case_record.id,
        topic_id=case_record.topic_id,
        topic_title=topic.title if topic else None,
        title=title,
        opened_at=case_record.opened_at,
        updated_at=case_record.updated_at,
        closed_at=case_record.closed_at,
        status=_clean_optional_string(case_record.status) or "open",
        actor_id=case_record.actor_id,
        source=_clean_optional_string(case_record.source),
        input_summary=_clean_optional_string(case_record.input_summary),
        summary_current=summary_current,
        files=_string_list(case_data.get("files")),
        symbols=_string_list(case_data.get("symbols")),
        errors=_string_list(case_data.get("errors")),
        symptoms=_string_list(case_data.get("symptoms")),
        commands=_commands_list(case_data.get("commands")),
        hypotheses=_hypotheses_list(case_data.get("hypotheses")),
        changes=_changes_list(case_data.get("changes")),
        outcome=_clean_optional_string(case_data.get("outcome")),
        next_steps=_string_list(case_data.get("next_steps")),
        context_pack_snapshot=snapshot,
    )


def build_default_case_data(_case_record: CaseRecord) -> dict[str, Any]:
    # Keep narrative scalars on CaseRecord columns, not inside the legacy JSON payload.
    return {
        "files": [],
        "symbols": [],
        "errors": [],
        "symptoms": [],
        "commands": [],
        "hypotheses": [],
        "changes": [],
        "outcome": None,
        "next_steps": [],
    }


def materialize_case_data(case: CasePublic) -> dict[str, Any]:
    payload = case.model_dump(mode="json")
    return {field: payload.get(field) for field in CASE_DATA_FIELDS}


def normalize_context_pack_snapshot(
    snapshot_payload: Any,
    *,
    topic_id: uuid.UUID,
    case_id: uuid.UUID,
) -> ContextPackSnapshot:
    payload = _json_object(snapshot_payload).copy()
    payload["topic_id"] = str(topic_id)
    payload["case_id"] = str(case_id)
    return ContextPackSnapshot(**payload)


def merge_context_pack_snapshot(
    current_snapshot: Any,
    patch_snapshot: Any,
    *,
    topic_id: uuid.UUID,
    case_id: uuid.UUID,
) -> dict[str, Any]:
    merged = _json_object(current_snapshot).copy()
    merged.update(_json_object(patch_snapshot))
    snapshot = normalize_context_pack_snapshot(
        merged,
        topic_id=topic_id,
        case_id=case_id,
    )
    return snapshot.model_dump(mode="json")


def apply_case_update(case_record: CaseRecord, update: dict[str, Any]) -> CaseRecord:
    now = get_datetime_utc()

    if "title" in update and update["title"] is not None:
        title = str(update["title"]).strip()
        if title:
            case_record.title = title
    if "status" in update and update["status"] is not None:
        status = str(update["status"]).strip()
        if status:
            case_record.status = status
            case_record.closed_at = now if is_terminal_case_status(status) else None
    if "actor_id" in update:
        case_record.actor_id = update["actor_id"]
    if "source" in update:
        case_record.source = _clean_optional_string(update.get("source"))
    if "input_summary" in update:
        case_record.input_summary = _clean_optional_string(update.get("input_summary"))
    if "summary_current" in update:
        case_record.summary_current = _clean_optional_string(update.get("summary_current"))

    case_data = _normalized_case_data(case_record.case_data)
    for key in CASE_DATA_FIELDS:
        if key in update:
            case_data[key] = update[key]
    case_record.case_data = case_data

    if "context_pack_snapshot" in update:
        case_record.context_pack_snapshot = merge_context_pack_snapshot(
            case_record.context_pack_snapshot,
            update.get("context_pack_snapshot"),
            topic_id=case_record.topic_id,
            case_id=case_record.id,
        )

    case_record.updated_at = now
    return case_record


def build_case_event(case_id: uuid.UUID, event_in: CaseEventCreate) -> CaseEvent:
    return CaseEvent(
        case_id=case_id,
        ts=event_in.ts or get_datetime_utc(),
        type=event_in.type,
        message=event_in.message,
        data=event_in.data,
        supersedes_event_id=event_in.supersedes_event_id,
    )


def build_case_event_public(case_event: CaseEvent) -> CaseEventPublic:
    return CaseEventPublic(
        id=case_event.id or 0,
        case_id=case_event.case_id,
        ts=case_event.ts,
        type=case_event.type,
        message=case_event.message,
        data=_json_object(case_event.data),
        supersedes_event_id=case_event.supersedes_event_id,
    )


def render_case_memo(case: CasePublic) -> CaseMemoView:
    return CaseMemoView(
        case_id=case.id,
        topic_id=case.topic_id,
        title=case.title,
        status=case.status,
        opened_at=case.opened_at,
        updated_at=case.updated_at,
        input_summary=case.input_summary,
        summary_current=case.summary_current,
        files=case.files,
        errors=case.errors,
        symptoms=case.symptoms,
        commands=case.commands,
        hypotheses=case.hypotheses,
        changes=case.changes,
        outcome=case.outcome,
        next_steps=case.next_steps,
    )


def render_case_hydration(case: CasePublic) -> CaseHydrationView:
    matched_signals = list(case.context_pack_snapshot.matched_signals)
    if not matched_signals:
        matched_signals = _matched_signals_from_case(case)

    supported_hypotheses = [
        hypothesis.statement for hypothesis in case.hypotheses if hypothesis.status == "supported"
    ]
    open_questions = [
        hypothesis.statement for hypothesis in case.hypotheses if hypothesis.status == "open"
    ]

    return CaseHydrationView(
        case_id=case.id,
        topic_id=case.topic_id,
        title=case.title,
        input_summary=case.input_summary,
        summary_current=case.summary_current,
        matched_signals=matched_signals,
        signals=CaseHydrationSignals(
            files=case.files,
            symbols=case.symbols,
            errors=case.errors,
            symptoms=case.symptoms,
        ),
        supported_hypotheses=supported_hypotheses,
        open_questions=open_questions,
        recent_changes=case.changes,
        next_steps=case.next_steps,
        context_pack_snapshot=case.context_pack_snapshot,
    )


def is_terminal_case_status(status: str | None) -> bool:
    if status is None:
        return False
    return status.strip().lower() in TERMINAL_CASE_STATUSES


def _commands_list(value: Any) -> list[CommandRecord]:
    records = _list_payload(value)
    return [CommandRecord(**record) for record in records]


def _hypotheses_list(value: Any) -> list[HypothesisRecord]:
    records = _list_payload(value)
    return [HypothesisRecord(**record) for record in records]


def _changes_list(value: Any) -> list[ChangeRecord]:
    records = _list_payload(value)
    return [ChangeRecord(**record) for record in records]


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _normalized_case_data(value: Any) -> dict[str, Any]:
    payload = _json_object(value)
    return {field: payload[field] for field in CASE_DATA_FIELDS if field in payload}


def _list_payload(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    cleaned: list[str] = []
    for item in value:
        text_value = _clean_optional_string(item)
        if text_value is not None:
            cleaned.append(text_value)
    return cleaned


def _clean_optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _matched_signals_from_case(case: CasePublic) -> list[str]:
    ordered = [*case.errors, *case.symptoms, *case.files, *case.symbols]
    seen: set[str] = set()
    signals: list[str] = []
    for signal in ordered:
        if signal in seen:
            continue
        seen.add(signal)
        signals.append(signal)
        if len(signals) >= 8:
            break
    return signals
