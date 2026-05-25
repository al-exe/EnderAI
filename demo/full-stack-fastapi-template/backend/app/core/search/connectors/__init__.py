"""Source connectors for Taskforce Search.

Each connector implements the ``Source`` protocol in ``base.py`` and
emits ``SourceItemRecord`` objects the indexer turns into rows in
``source_item_embedding``. Phase 1 ships one real connector
(``DocumentSource``) plus a deliberate stub so the abstraction stays
honest before we go add Slack / GitHub / Gmail / GDocs."""

from app.core.search.connectors.base import Source
from app.core.search.connectors.documents import DocumentSource

__all__ = ["Source", "DocumentSource"]
