"""Search retrieval — ACL-aware hybrid lookup.

Phase 1 is vector-only: embed the query, sort source_item_embedding
rows by cosine distance, take top-K. ACL enforcement is the
load-bearing piece — we JOIN to ``v2_document`` and reuse
``build_v2_document_acl_filter`` so the existing read path and the
search path stay in lockstep. The denormalized columns on
``source_item_embedding`` (owner_id / organization_id / visibility /
is_demo) are belt-and-suspenders; the actual gate is the JOIN.

Future Phase 2 work will layer FTS for naked-keyword queries. The
SearchHit shape is the contract that change won't break."""

from __future__ import annotations

import logging
import uuid

from sqlmodel import Session, col, select

from app.core.search.embeddings import embed_one
from app.core.search.types import SearchHit
from app.core.v2_documents import build_v2_document_acl_filter
from app.models import SourceItemEmbedding, User, V2Document

log = logging.getLogger(__name__)

DEFAULT_TOP_K = 8
MAX_TOP_K = 20


async def retrieve(
    *,
    session: Session,
    actor: User,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    demo: bool = False,
) -> list[SearchHit]:
    """Return up to ``top_k`` chunks the actor is allowed to read,
    sorted by cosine similarity to the query."""

    if top_k < 1:
        return []
    top_k = min(top_k, MAX_TOP_K)

    query_vec = await embed_one(query)

    # Build the joined query. We constrain to source_kind="documents"
    # because that's the only connector that's actually indexed in
    # Phase 1; once Slack/etc land, retrieval will branch per source
    # so each connector can supply its own ACL helper.
    acl = build_v2_document_acl_filter(actor, demo=demo)

    distance = col(SourceItemEmbedding.embedding).cosine_distance(query_vec)

    statement = (
        select(
            SourceItemEmbedding,
            V2Document,
            distance.label("dist"),
        )
        .join(
            V2Document,
            col(V2Document.id) == col(SourceItemEmbedding.source_item_id).cast(uuid.UUID),  # type: ignore[arg-type]
        )
        .where(SourceItemEmbedding.source_kind == "documents")
        .where(SourceItemEmbedding.is_demo.is_(demo))  # type: ignore[union-attr]
        .where(acl)
        .order_by(col("dist").asc())
        .limit(top_k)
    )

    rows = session.exec(statement).all()

    hits: list[SearchHit] = []
    for row in rows:
        emb, doc, dist = row
        # cosine_distance() returns distance in [0, 2]; turn into a
        # 0..1-ish similarity for prompt context + UI.
        score = max(0.0, 1.0 - float(dist) / 2.0)
        hits.append(
            SearchHit(
                source_kind=emb.source_kind,
                source_item_id=emb.source_item_id,
                chunk_anchor_id=emb.chunk_anchor_id,
                chunk_text=emb.chunk_text,
                title=doc.title,
                url_path=f"/v2/library/{doc.id}",
                score=score,
            )
        )
    return hits
