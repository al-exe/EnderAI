import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from app.models import (
    CaseHydrationSignals,
    CaseHydrationView,
    CaseMemoView,
    CasePublic,
    ContextPackSnapshot,
)

CASE_DATA_FIELDS = {
    "title",
    "actor_id",
    "source",
    "input_summary",
    "summary_current",
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

TERMINAL_CASE_STATUSES = {"done", "aborted", "failed", "success", "error", "closed"}


def execution_has_column(session: Session, column_name: str) -> bool:
    stmt = text(
        "select 1 "
        "from information_schema.columns "
        "where table_schema = 'public' and table_name = 'execution' and column_name = :column_name "
        "limit 1"
    )
    return (
        session.connection().execute(stmt, {"column_name": column_name}).first() is not None
    )


def build_default_case_data(
    execution_row: dict[str, Any],
    thread_row: dict[str, Any],
) -> dict[str, Any]:
    summary = _clean_optional_string(execution_row.get("summary"))
    title = summary or _clean_optional_string(thread_row.get("title")) or "Case"
    actor_id = execution_row.get("actor_id") or None
    if isinstance(actor_id, uuid.UUID):
        actor_id = str(actor_id)
    return {
        "title": title,
        "actor_id": actor_id,
        "source": None,
        "input_summary": None,
        "summary_current": summary,
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


def build_case_public(execution_row: dict[str, Any], thread_row: dict[str, Any]) -> CasePublic:
    case_data = build_default_case_data(execution_row, thread_row)
    case_data.update(_json_object(execution_row.get("case_data")))

    summary_current = _clean_optional_string(execution_row.get("summary"))
    if summary_current is None:
        summary_current = _clean_optional_string(case_data.get("summary_current"))
    case_data["summary_current"] = summary_current

    title = _clean_optional_string(case_data.get("title"))
    if title is None:
        title = _clean_optional_string(thread_row.get("title")) or summary_current or "Case"
        case_data["title"] = title

    snapshot_payload = _json_object(execution_row.get("context_pack_snapshot"))
    snapshot_payload.setdefault("topic_id", str(thread_row["id"]))
    snapshot_payload.setdefault("case_id", str(execution_row["id"]))
    snapshot = ContextPackSnapshot(**snapshot_payload)

    updated_at = (
        execution_row.get("updated_at")
        or execution_row.get("ended_at")
        or execution_row.get("started_at")
    )

    return CasePublic(
        id=execution_row["id"],
        topic_id=thread_row["id"],
        title=title,
        opened_at=execution_row.get("started_at"),
        updated_at=updated_at,
        closed_at=execution_row.get("ended_at"),
        status=_clean_optional_string(execution_row.get("status")) or "open",
        actor_id=case_data.get("actor_id"),
        source=_clean_optional_string(case_data.get("source")),
        input_summary=_clean_optional_string(case_data.get("input_summary")),
        summary_current=summary_current,
        files=_string_list(case_data.get("files")),
        symbols=_string_list(case_data.get("symbols")),
        errors=_string_list(case_data.get("errors")),
        symptoms=_string_list(case_data.get("symptoms")),
        commands=_list_payload(case_data.get("commands")),
        hypotheses=_list_payload(case_data.get("hypotheses")),
        changes=_list_payload(case_data.get("changes")),
        outcome=_clean_optional_string(case_data.get("outcome")),
        next_steps=_string_list(case_data.get("next_steps")),
        context_pack_snapshot=snapshot,
    )


def materialize_case_data(case: CasePublic) -> dict[str, Any]:
    payload = case.model_dump(mode="json")
    return {field: payload.get(field) for field in CASE_DATA_FIELDS}


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


def _json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    if isinstance(value, dict):
        return value
    return {}


def _list_payload(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
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
