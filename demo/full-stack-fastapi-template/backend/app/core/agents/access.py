from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_

from app.models import AgentSpecialist, User


def build_agent_specialist_acl_filter(actor: User, *, demo: bool) -> Any:
    """SQLAlchemy filter expression for specialists this actor may read."""

    if demo:
        return AgentSpecialist.is_demo.is_(True)  # type: ignore[union-attr]

    org_clause = (
        and_(
            AgentSpecialist.visibility == "organization",
            AgentSpecialist.organization_id == actor.organization_id,
        )
        if actor.organization_id is not None
        else AgentSpecialist.id.is_(None)  # type: ignore[union-attr] -- always false
    )
    return and_(
        AgentSpecialist.is_demo.is_(False),  # type: ignore[union-attr]
        or_(
            AgentSpecialist.owner_id == actor.id,
            org_clause,
        ),
    )
