"""Source protocol every Search connector implements."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar, Iterable, Protocol, runtime_checkable

from sqlmodel import Session

from app.core.search.types import SourceItemRecord


@runtime_checkable
class Source(Protocol):
    """The minimal contract for anything Search can index.

    Three responsibilities:

    - ``list_items`` is the backfill / drift sweep entrypoint. Given an
      owner and an optional ``since`` watermark, yield every record
      that's new or changed. The indexer pages through this with a
      hard limit so a single sweep can't starve out other sources.

    - ``fetch_item`` is the single-row refresh. Used by tests and the
      admin backfill CLI; not on the hot path.

    - ``handle_event`` is the webhook entrypoint. Phase 1 connectors
      can raise NotImplementedError; this exists so the indexer keeps
      a uniform shape when we layer in Slack / GitHub etc."""

    kind: ClassVar[str]

    async def list_items(
        self,
        *,
        session: Session,
        owner_id: uuid.UUID | None = None,
        since: datetime | None = None,
        limit: int = 50,
    ) -> Iterable[SourceItemRecord]:
        ...

    async def fetch_item(
        self,
        *,
        session: Session,
        source_item_id: str,
    ) -> SourceItemRecord | None:
        ...

    async def handle_event(
        self,
        *,
        session: Session,
        payload: dict[str, Any],
    ) -> Iterable[SourceItemRecord]:
        ...
