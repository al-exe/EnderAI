"""Earned-profile compounding (TF-205 / C6) — DESIGN STUB, not yet wired.

The Taskforce loop is *raw input -> clean agent profiles -> redropped in*. This
module is the middle arrow's **earned** path: an offline, out-of-loop job that turns
``AgentSpecialist`` rows from ``created_from="seeded"`` into ``"earned"`` by accreting
``AgentSpecialistDocumentLink`` rows from the real ``V2Document``s that match a
specialist's routing signals.

Why it exists (thesis D5): seeded profiles look like a shared-prompt library (the
commodity); *earned* profiles are the moat — "we capture what your agents figure out,
not what you write down." This compounding is that capture, consolidated.

Hard rule: this runs **off the agent's critical path** (a worker / scheduled task),
never from ``route_specialist`` or any request handler — sensor, not processor.

Full design (algorithm, reused helpers, guardrails): ``docs/planning/earned-profiles-design.md``.

This module is intentionally NOT imported anywhere yet — implementing the body is the
build step that follows the design. Reuse ``app.core.taskforce.scoring.score_document``,
``app.core.v2_documents.list_v2_documents_for_actor``, and the
``AgentSpecialistDocumentLink`` unique constraint (idempotent upsert).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # keep module import light — no DB/config at load time
    from sqlmodel import Session

# Tunables (see design doc §Guardrails). Start values; regress from real data later.
MIN_LINK_SCORE = 0.45
MAX_LINKS_PER_SPECIALIST = 25


def compound_specialists(
    session: "Session",
    *,
    organization_id: uuid.UUID | None = None,
    min_link_score: float = MIN_LINK_SCORE,
    max_links_per_specialist: int = MAX_LINKS_PER_SPECIALIST,
    dry_run: bool = True,
) -> dict[str, int]:
    """Accrete earned doc-links onto an org's specialists; flip ``created_from``.

    Returns a summary, e.g. ``{"specialists_seen": N, "links_created": M,
    "links_updated": K, "promoted_to_earned": P}``. With ``dry_run=True`` (default)
    it computes the plan and writes nothing — mirroring ``observe.py`` shadow mode.

    NOT YET IMPLEMENTED — see ``docs/planning/earned-profiles-design.md``.
    """

    raise NotImplementedError(
        "Earned-profile compounding is designed but not yet built — "
        "see docs/planning/earned-profiles-design.md (TF-205 / C6)."
    )
