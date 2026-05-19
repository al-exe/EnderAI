"""Versioned model-pricing lookup.

Every metrics event that records a USD figure must be priced against the
ModelPricing row that was effective at the moment the event occurred, and the
event row stores that pricing_id as a frozen audit trail. ``pricing_for``
encapsulates the lookup so callers never have to think about effective_from /
effective_to windowing.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.models import ModelPricing


def pricing_for(
    session: Session,
    model_id: str,
    occurred_at: datetime,
) -> ModelPricing | None:
    """Return the ``ModelPricing`` row valid for ``model_id`` at ``occurred_at``.

    A row is valid when:
      * ``effective_from <= occurred_at``
      * ``effective_to`` is ``NULL`` (still current) or strictly greater than
        ``occurred_at`` (the new row took effect after the event).

    When multiple rows overlap (which shouldn't happen if the catalog is
    maintained correctly but is permitted by the schema's unique constraint
    on ``(model_id, effective_from)`` alone), the row with the most recent
    ``effective_from`` wins — i.e. we honour the latest applicable price.

    Returns ``None`` when no row matches; callers that need a USD figure
    should treat that as "skip the dollar calculation and just record the
    token counts".
    """

    statement = (
        select(ModelPricing)
        .where(
            ModelPricing.model_id == model_id,
            col(ModelPricing.effective_from) <= occurred_at,
            or_(
                col(ModelPricing.effective_to).is_(None),
                col(ModelPricing.effective_to) > occurred_at,
            ),
        )
        .order_by(col(ModelPricing.effective_from).desc())
        .limit(1)
    )
    return session.exec(statement).first()
