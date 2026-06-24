"""Taskforce V2 Search — retrieval-augmented chat over user content.

See /home/alexlee/.claude/plans/parsed-dancing-tide.md for the full plan
and ``app/core/search/connectors/`` for the per-source adapters.

The legacy V1 global search (``search_topics_and_cases``, used by
``/api/v1/search/``) lives in ``legacy.py`` inside this package — it
was at ``app/core/search.py`` before V2 Search added a package here
and shadowed it. We re-export the V1 entrypoint at the package root
so existing callers (``app/api/routes/search.py``) don't have to
change their imports."""

from app.core.search.global_search import search_global  # noqa: F401
from app.core.search.legacy import search_topics_and_cases  # noqa: F401

__all__ = ["search_global", "search_topics_and_cases"]
