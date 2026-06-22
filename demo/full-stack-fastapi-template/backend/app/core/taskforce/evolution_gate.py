"""Org + env gate for the self-evolving knowledge layer (T7).

Every auto-write path (evolution orchestrator, future T1/T2/T4) must call
``can_auto_evolve`` before mutating docs or profiles. Capture and summarize
stay unconditional — this only gates automatic creation/updates.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlmodel import Session

from app.core.config import settings
from app.models import Organization

AutoEvolveBlockReason = Literal["disabled_env", "disabled_org"]


@dataclass(frozen=True)
class AutoEvolveEligibility:
    allowed: bool
    reason: AutoEvolveBlockReason | None = None


def can_auto_evolve(
    session: Session,
    *,
    organization_id: uuid.UUID | None,
) -> AutoEvolveEligibility:
    """Return whether offline evolution may auto-create or auto-update."""

    if not settings.TF_SELF_EVOLVE:
        return AutoEvolveEligibility(allowed=False, reason="disabled_env")

    if organization_id is None:
        # Solo users without an org row: no org switch to turn off.
        return AutoEvolveEligibility(allowed=True)

    organization = session.get(Organization, organization_id)
    if organization is not None and not organization.auto_evolve_enabled:
        return AutoEvolveEligibility(allowed=False, reason="disabled_org")

    return AutoEvolveEligibility(allowed=True)
