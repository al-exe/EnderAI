"""Session harness provenance helpers (client / harness_label).

Cursor, Codex, and Claude Code all report ``client`` on hook payloads, but
the shared Taskforce MCP server may default to ``claude-code`` when a
hookless tool call omits ``client``. Never let that default clobber a
stronger hook-reported value (e.g. Cursor hooks → ``cursor``).
"""

from __future__ import annotations

# Higher wins when two known clients disagree. ``claude-code`` is the MCP
# fallback and must not override hook-exclusive harnesses.
_CLIENT_PRIORITY: dict[str, int] = {
    "cursor": 3,
    "codex": 3,
    "claude-code": 2,
    "claude": 2,
}


def _normalize_client(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def merge_session_client(
    existing: str | None,
    incoming: str | None,
) -> str | None:
    """Merge self-reported session client provenance without cross-harness clobber."""

    inc = _normalize_client(incoming)
    if inc is None:
        return existing
    ex = _normalize_client(existing)
    if ex is None:
        return inc
    if ex == inc:
        return existing
    if _CLIENT_PRIORITY.get(inc, 0) > _CLIENT_PRIORITY.get(ex, 0):
        return inc
    return existing


def resolve_session_client(*values: str | None) -> str | None:
    """Pick the strongest harness label across all known provenance fields."""

    resolved: str | None = None
    for value in values:
        resolved = merge_session_client(resolved, value)
    return resolved


def sync_session_provenance(
    *,
    client: str | None,
    harness_label: str | None,
    incoming: str | None,
) -> tuple[str | None, str | None]:
    """Merge incoming provenance and keep ``client`` / ``harness_label`` aligned."""

    canonical = resolve_session_client(client, harness_label, incoming)
    return canonical, canonical
