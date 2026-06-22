"""Bounded content patches + changelog/revert for offline doc evolution (T2)."""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, col, select

from app.core.v2_documents import apply_v2_document_update, get_v2_document_for_actor
from app.core.taskforce.evolution_summary import (
    EVOLUTION_SUMMARY_KEY,
    StoredEvolutionSummary,
    stored_summary_from_metadata,
    summary_has_content,
)
from app.core.taskforce.summarizer import SummarizerResult
from app.models import (
    TaskforceSessionArchive,
    User,
    V2Document,
    V2DocumentDetailsSection,
    V2DocumentEvolutionChangelog,
    V2DocumentParagraph,
    V2DocumentSegment,
    V2DocumentUpdate,
    get_datetime_utc,
)

REFERENCED_BY_ANCHOR_ID = "referenced-by"
EVOLUTION_APPEND_ANCHOR_ID = "evolution-append"


def _format_reference_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _document_details_sections(
    document: V2Document,
) -> list[V2DocumentDetailsSection]:
    return [
        V2DocumentDetailsSection.model_validate(section)
        for section in document.details_markdown_sections or []
    ]


def _paragraph_text(paragraph: dict[str, Any] | V2DocumentParagraph) -> str:
    if isinstance(paragraph, V2DocumentParagraph):
        segments = paragraph.segments
    else:
        segments = paragraph.get("segments") or []
    parts: list[str] = []
    for segment in segments:
        text = (
            segment.text
            if isinstance(segment, V2DocumentSegment)
            else segment.get("text")
        )
        if text:
            parts.append(str(text))
    return " ".join(parts)


def _document_body_text(document: V2Document) -> str:
    return "\n".join(
        _paragraph_text(paragraph) for paragraph in (document.main_body or [])
    )


def _novel_summary_points(
    document: V2Document, summary_points: list[str]
) -> list[str]:
    corpus = _document_body_text(document).lower()
    novel: list[str] = []
    for point in summary_points:
        stripped = point.strip()
        if not stripped:
            continue
        if stripped.lower() in corpus:
            continue
        novel.append(stripped)
    return novel


def _append_reference_row(
    sections: list[V2DocumentDetailsSection], row: str
) -> list[V2DocumentDetailsSection]:
    referenced_by = next(
        (section for section in sections if section.anchor_id == REFERENCED_BY_ANCHOR_ID),
        None,
    )
    if referenced_by is None:
        referenced_by = V2DocumentDetailsSection(
            anchor_id=REFERENCED_BY_ANCHOR_ID,
            markdown="",
        )
        sections.append(referenced_by)
    rows = [line for line in referenced_by.markdown.splitlines() if line.strip()]
    rows.append(row)
    referenced_by.markdown = "\n".join(rows[-20:])
    return sections


def _merge_details_sections(
    existing: list[V2DocumentDetailsSection],
    incoming: list[dict[str, str]],
) -> list[V2DocumentDetailsSection]:
    by_anchor = {section.anchor_id: section for section in existing}
    for raw in incoming:
        anchor_id = str(raw.get("anchor_id") or "").strip()
        markdown = str(raw.get("markdown") or "").strip()
        if not anchor_id or not markdown:
            continue
        if anchor_id in by_anchor:
            current = by_anchor[anchor_id].markdown.strip()
            if markdown not in current:
                by_anchor[anchor_id].markdown = (
                    f"{current}\n\n{markdown}" if current else markdown
                )
        else:
            by_anchor[anchor_id] = V2DocumentDetailsSection(
                anchor_id=anchor_id,
                markdown=markdown,
            )
    return list(by_anchor.values())


def _evolution_reference_row(archive: TaskforceSessionArchive) -> str:
    timestamp = _format_reference_timestamp(get_datetime_utc())
    session_short = (archive.session_id or "")[:8]
    title = (archive.title or "session").replace('"', "'")[:120]
    return (
        f"- **{timestamp}** · session `{session_short}` · "
        f'auto-evolved from "{title}"'
    )


def snapshot_document_content(document: V2Document) -> dict[str, Any]:
    return {
        "title": document.title,
        "description": document.description,
        "human_summary": document.human_summary,
        "ai_generated_summary": document.ai_generated_summary,
        "main_body": deepcopy(document.main_body or []),
        "details_markdown_sections": deepcopy(
            document.details_markdown_sections or []
        ),
    }


def build_merged_evolution_update(
    document: V2Document,
    *,
    summary: SummarizerResult,
    archive: TaskforceSessionArchive,
) -> tuple[V2DocumentUpdate, dict[str, Any]]:
    """Append-only merge from a session summary; returns update + diff metadata."""

    novel_points = _novel_summary_points(document, summary.summary_points)
    merged_body = list(document.main_body or [])
    for point in novel_points:
        merged_body.append(
            V2DocumentParagraph(segments=[V2DocumentSegment(text=point)]).model_dump(
                mode="json"
            )
        )

    sections = _document_details_sections(document)
    if summary.details_sections:
        sections = _merge_details_sections(
            sections,
            [section for section in summary.details_sections if isinstance(section, dict)],
        )
    reference_row = _evolution_reference_row(archive)
    sections = _append_reference_row(sections, reference_row)

    next_summary = document.ai_generated_summary or ""
    if novel_points:
        appended = " ".join(novel_points)[:600]
        next_summary = (
            f"{next_summary} {appended}".strip()[:600]
            if next_summary
            else appended
        )

    update = V2DocumentUpdate(
        main_body=merged_body,
        details_markdown_sections=sections,
        ai_generated_summary=next_summary or document.ai_generated_summary,
    )
    diff = {
        "appended_summary_points": novel_points,
        "referenced_by_row": reference_row,
        "details_sections_added": len(summary.details_sections or []),
    }
    return update, diff


def apply_evolution_patch(
    session: Session,
    *,
    actor: User,
    document: V2Document,
    archive: TaskforceSessionArchive,
    stored: StoredEvolutionSummary,
    summary: SummarizerResult,
    match_score: float,
) -> V2DocumentEvolutionChangelog | None:
    """Patch a matched document and record a revertable changelog row."""

    update, diff = build_merged_evolution_update(
        document, summary=summary, archive=archive
    )
    if not diff["appended_summary_points"] and not summary.details_sections:
        return None

    revertable_to = snapshot_document_content(document)
    apply_v2_document_update(document, update)
    confidence = min(1.0, max(stored.materiality_score, match_score))
    document.evolution_confidence = confidence
    provenance = dict(document.evolution_provenance or {})
    provenance["last_auto_update"] = {
        "source_session_id": archive.session_id,
        "match_score": match_score,
        "confidence": confidence,
    }
    document.evolution_provenance = provenance
    session.add(document)

    changelog = V2DocumentEvolutionChangelog(
        document_id=document.id,
        actor_id=actor.id,
        source_session_id=archive.session_id,
        confidence=confidence,
        summary_snapshot={
            "summary_points": list(stored.summary_points),
            "details_sections": list(stored.details_sections),
            "decisions": list(stored.decisions),
            "outcome": stored.outcome,
        },
        diff_or_section=diff,
        revertable_to=revertable_to,
    )
    session.add(changelog)
    session.flush()
    return changelog


def revert_evolution_changelog(
    session: Session,
    *,
    actor: User,
    document_id: uuid.UUID,
    changelog_id: uuid.UUID,
    demo: bool,
) -> V2Document:
    document = get_v2_document_for_actor(session, actor, document_id, demo=demo)
    if document is None:
        raise ValueError("document_not_found")

    changelog = session.get(V2DocumentEvolutionChangelog, changelog_id)
    if changelog is None or changelog.document_id != document.id:
        raise ValueError("changelog_not_found")
    if changelog.reverted_at is not None:
        raise ValueError("changelog_already_reverted")

    snapshot = changelog.revertable_to or {}
    restore = V2DocumentUpdate(
        title=snapshot.get("title", document.title),
        description=snapshot.get("description", document.description),
        human_summary=snapshot.get("human_summary", document.human_summary),
        ai_generated_summary=snapshot.get(
            "ai_generated_summary", document.ai_generated_summary
        ),
        main_body=list(snapshot.get("main_body") or []),
        details_markdown_sections=[
            V2DocumentDetailsSection.model_validate(section)
            for section in snapshot.get("details_markdown_sections") or []
        ],
    )
    apply_v2_document_update(document, restore)
    changelog.reverted_at = get_datetime_utc()
    session.add(document)
    session.add(changelog)
    session.flush()
    return document


def list_evolution_changelogs(
    session: Session, *, document_id: uuid.UUID
) -> list[V2DocumentEvolutionChangelog]:
    return list(
        session.exec(
            select(V2DocumentEvolutionChangelog)
            .where(V2DocumentEvolutionChangelog.document_id == document_id)
            .order_by(col(V2DocumentEvolutionChangelog.created_at).desc())
        ).all()
    )
