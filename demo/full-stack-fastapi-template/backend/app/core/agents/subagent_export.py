"""Render an ``AgentSpecialist`` as a native subagent file (WS4a / TF-254).

Pure, deterministic string rendering — **no DB, no I/O, no request path**. The
sync layer (WS4b / TF-255) resolves ORM rows into :class:`ExportSpecialist` and
writes the result to ``.claude/agents/<slug>.md`` (canonical; also read by
Cursor), then the Codex target.

Format + field mapping live in
``docs/planning/agent-profiles-native-subagent-parity.md`` (WS5). Keeping this a
pure function of value objects is what makes it golden-file testable and lets the
Details payload (WS3) refine the embedded content without touching this layer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

# Char budgets approximate token budgets (~4 chars/token). Conservative starts;
# regress from real usage later. Per-doc bounds each embedded excerpt; the total
# bounds the whole "## Documents" section (lowest-priority docs are dropped).
DEFAULT_MAX_DOC_CHARS = 800
DEFAULT_MAX_DOCS_CHARS = 4000

# Claude Code (and Cursor) read this directory; it is the canonical export target.
CLAUDE_AGENTS_DIR = ".claude/agents"

# A read-only profile is granted a safe, inspect-only toolset. A "full" profile
# omits the ``tools`` line entirely so the harness lets it inherit everything.
READONLY_TOOLS: tuple[str, ...] = ("Read", "Grep", "Glob", "WebFetch")


@dataclass(frozen=True)
class ExportDocument:
    """One library document assigned to a profile, ready to embed."""

    title: str
    purpose: str = ""  # one-line human summary (fallback when details is empty)
    details: str = ""  # AI-friendly Details payload (WS3); may be empty for now
    backlink: str = ""  # link back to the human-readable document
    weight: float = 1.0  # ranking weight (earned score or manual)
    is_pinned: bool = False  # manual pins survive pruning first


@dataclass(frozen=True)
class ExportSpecialist:
    """The value object the renderer consumes — a harness-agnostic profile."""

    slug: str
    short_description: str = ""
    routing_triggers: list[str] = field(default_factory=list)
    negative_triggers: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    model_hint: str = "inherit"
    permission_scope: str = "readonly"
    documents: list[ExportDocument] = field(default_factory=list)


def subagent_filename(slug: str) -> str:
    """Canonical filename for a slug (no directory)."""

    return f"{slug}.md"


def subagent_content_hash(rendered: str) -> str:
    """Stable hash of a rendered file; WS4b rewrites only when this changes."""

    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def render_claude_subagent(
    spec: ExportSpecialist,
    *,
    max_doc_chars: int = DEFAULT_MAX_DOC_CHARS,
    max_docs_chars: int = DEFAULT_MAX_DOCS_CHARS,
) -> str:
    """Render ``spec`` as a Claude Code subagent markdown file.

    Deterministic: same input → byte-identical output.
    """

    front = _frontmatter(spec)
    instructions_block = "\n".join(_clean(spec.instructions))
    documents_block = _documents_block(
        spec.documents,
        max_doc_chars=max_doc_chars,
        max_docs_chars=max_docs_chars,
    )
    body = "\n\n".join(part for part in (instructions_block, documents_block) if part)
    return f"{front}\n{body}\n" if body else f"{front}\n"


def _frontmatter(spec: ExportSpecialist) -> str:
    lines = ["---", f"name: {spec.slug}", "description: |-"]
    lines.extend(f"  {line}" for line in _description_lines(spec))
    lines.append(f"model: {(spec.model_hint or 'inherit').strip() or 'inherit'}")
    tools = _tools_for_scope(spec.permission_scope)
    if tools:
        lines.append(f"tools: {', '.join(tools)}")
    lines.append("---")
    return "\n".join(lines)


def _description_lines(spec: ExportSpecialist) -> list[str]:
    lines: list[str] = []
    summary = (spec.short_description or "").strip()
    if summary:
        lines.append(summary)
    positive = _clean(spec.routing_triggers)
    if positive:
        lines.append(f"Use when: {', '.join(positive)}.")
    negative = _clean(spec.negative_triggers)
    if negative:
        lines.append(f"Do NOT use when: {', '.join(negative)}.")
    if not lines:
        lines.append(f"Taskforce specialist: {spec.slug}.")
    return lines


def _tools_for_scope(permission_scope: str) -> tuple[str, ...]:
    if (permission_scope or "readonly").strip().lower() == "full":
        return ()  # omit the tools line → inherit all harness tools
    return READONLY_TOOLS


def _documents_block(
    documents: list[ExportDocument],
    *,
    max_doc_chars: int,
    max_docs_chars: int,
) -> str:
    kept = _prune_documents(
        documents,
        max_doc_chars=max_doc_chars,
        max_docs_chars=max_docs_chars,
    )
    if not kept:
        return ""

    sections: list[str] = []
    for document in kept:
        section = [f"### {document.title.strip() or 'Untitled document'}"]
        excerpt = _excerpt(document, max_doc_chars)
        if excerpt:
            section.append(excerpt)
        backlink = document.backlink.strip()
        if backlink:
            section.append(f"↳ {backlink}")
        sections.append("\n".join(section))
    return "## Documents\n\n" + "\n\n".join(sections)


def _prune_documents(
    documents: list[ExportDocument],
    *,
    max_doc_chars: int,
    max_docs_chars: int,
) -> list[ExportDocument]:
    # Deterministic priority: pinned first, then heavier weight, then title.
    ordered = sorted(
        documents,
        key=lambda document: (
            not document.is_pinned,
            -document.weight,
            document.title.strip().lower(),
        ),
    )
    kept: list[ExportDocument] = []
    running = 0
    for document in ordered:
        cost = len(document.title) + len(_excerpt(document, max_doc_chars)) + len(
            document.backlink
        )
        if kept and running + cost > max_docs_chars:
            break  # keep the highest-priority docs that fit; drop the tail
        kept.append(document)
        running += cost
    return kept


def _excerpt(document: ExportDocument, limit: int) -> str:
    source = (document.details or document.purpose or "").strip()
    return _truncate(source, limit)


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if limit <= 0 or len(text) <= limit:
        return text if limit > 0 else ""
    return text[: max(0, limit - 1)].rstrip() + "…"


def _clean(values: list[str]) -> list[str]:
    """Strip, drop blanks, de-dupe case-insensitively, preserve order."""

    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        stripped = (value or "").strip()
        key = stripped.lower()
        if stripped and key not in seen:
            seen.add(key)
            out.append(stripped)
    return out
