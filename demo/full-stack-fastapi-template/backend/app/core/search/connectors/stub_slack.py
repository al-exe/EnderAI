"""Deliberate stub connector that proves the Source protocol compiles
for a non-Documents source. NOT registered with the indexer yet —
the indexer will pick this up when Phase 2 lands a real Slack adapter.

Keeping a non-trivial stub in-tree forces the abstraction to stay
honest: if someone changes ``Source`` in a way that breaks future
connectors, this file fails to type-check or import."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar, Iterable, NoReturn

from sqlmodel import Session

from app.core.search.types import SourceItemRecord


class StubSlackSource:
    kind: ClassVar[str] = "slack"

    async def list_items(  # noqa: ARG002 -- stub signature
        self,
        *,
        session: Session,
        owner_id: uuid.UUID | None = None,
        since: datetime | None = None,
        limit: int = 50,
    ) -> Iterable[SourceItemRecord]:
        self._not_implemented()

    async def fetch_item(  # noqa: ARG002 -- stub signature
        self,
        *,
        session: Session,
        source_item_id: str,
    ) -> SourceItemRecord | None:
        self._not_implemented()

    async def handle_event(  # noqa: ARG002 -- stub signature
        self,
        *,
        session: Session,
        payload: dict[str, Any],
    ) -> Iterable[SourceItemRecord]:
        self._not_implemented()

    @staticmethod
    def _not_implemented() -> NoReturn:
        raise NotImplementedError(
            "Slack source is not implemented in Phase 1. See the search plan "
            "for the connector roadmap."
        )
