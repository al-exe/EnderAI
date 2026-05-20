"""Retrieval ACL — load-bearing security test.

Confirms that no matter how the corpus is laid out, Search retrieval
never returns chunks the actor can't read via the regular Documents
read path. Embedding generation is monkeypatched to a deterministic
hash so tests don't hit OpenAI."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlmodel import Session, select

from app.core.search import embeddings as embeddings_module
from app.core.search import indexing as indexing_module
from app.core.search.connectors.documents import DocumentSource
from app.core.search.retrieval import retrieve
from app.models import (
    Organization,
    SourceItemEmbedding,
    User,
    V2Document,
    V2DocumentShare,
)
from tests.utils.user import create_random_user


def _stub_vec(text: str) -> list[float]:
    """Deterministic, low-dimension stand-in for an embedding.

    We hash the text into 1536 floats in [-1, 1]. Two identical
    strings produce identical vectors, so a Search query that
    *exactly* matches a chunk text gets perfect similarity. That's all
    we need to validate the retrieval pipeline + ACL filter."""

    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Repeat the 32-byte digest until we have 1536 floats.
    blob = (digest * ((1536 // len(digest)) + 1))[:1536]
    return [(b - 128) / 128.0 for b in blob]


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_embed_batch(texts):  # type: ignore[no-untyped-def]
        return [_stub_vec(t) for t in texts]

    async def fake_embed_one(text):  # type: ignore[no-untyped-def]
        return _stub_vec(text)

    async def fake_safe_embed_batch(texts):  # type: ignore[no-untyped-def]
        return [_stub_vec(t) for t in texts]

    monkeypatch.setattr(embeddings_module, "embed_batch", fake_embed_batch)
    monkeypatch.setattr(embeddings_module, "embed_one", fake_embed_one)
    monkeypatch.setattr(
        embeddings_module, "safe_embed_batch", fake_safe_embed_batch
    )
    monkeypatch.setattr(indexing_module, "safe_embed_batch", fake_safe_embed_batch)


def _make_doc(
    db: Session,
    owner: User,
    *,
    title: str,
    chunk_text: str,
    visibility: str = "private",
    organization_id: uuid.UUID | None = None,
) -> V2Document:
    doc = V2Document(
        owner_id=owner.id,
        organization_id=organization_id,
        title=title,
        visibility=visibility,
        human_summary=chunk_text,
        details_markdown_sections=[
            {"anchor_id": "main", "markdown": chunk_text}
        ],
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


async def _index(db: Session, doc: V2Document) -> None:
    source = DocumentSource()
    rec = await source.fetch_item(session=db, source_item_id=str(doc.id))
    assert rec is not None
    await indexing_module.upsert_record(db, rec)
    db.commit()


@pytest.mark.asyncio
async def test_owner_can_retrieve_own_private_doc(db: Session) -> None:
    owner = create_random_user(db)
    doc = _make_doc(
        db, owner, title="Owner Doc", chunk_text="findings about widgets"
    )
    await _index(db, doc)

    hits = await retrieve(
        session=db, actor=owner, query="findings about widgets", top_k=5
    )
    assert any(h.source_item_id == str(doc.id) for h in hits)


@pytest.mark.asyncio
async def test_cannot_retrieve_other_users_private_doc(db: Session) -> None:
    owner = create_random_user(db)
    intruder = create_random_user(db)
    doc = _make_doc(
        db, owner, title="Private", chunk_text="secret findings xyz"
    )
    await _index(db, doc)

    hits = await retrieve(
        session=db, actor=intruder, query="secret findings xyz", top_k=5
    )
    assert all(h.source_item_id != str(doc.id) for h in hits)


@pytest.mark.asyncio
async def test_org_visible_doc_reachable_by_org_member(db: Session) -> None:
    org = Organization(name=f"acme-{uuid.uuid4().hex[:8]}")
    db.add(org)
    db.commit()
    db.refresh(org)
    owner = create_random_user(db)
    member = create_random_user(db)
    owner.organization_id = org.id
    member.organization_id = org.id
    db.add(owner)
    db.add(member)
    db.commit()

    doc = _make_doc(
        db,
        owner,
        title="Org Doc",
        chunk_text="quarterly review findings",
        visibility="organization",
        organization_id=org.id,
    )
    await _index(db, doc)

    hits = await retrieve(
        session=db,
        actor=member,
        query="quarterly review findings",
        top_k=5,
    )
    assert any(h.source_item_id == str(doc.id) for h in hits)


@pytest.mark.asyncio
async def test_explicit_share_grants_retrieval(db: Session) -> None:
    owner = create_random_user(db)
    other = create_random_user(db)
    doc = _make_doc(
        db, owner, title="Shared", chunk_text="findings shared explicitly"
    )
    share = V2DocumentShare(
        document_id=doc.id, user_id=other.id, permission="viewer"
    )
    db.add(share)
    db.commit()
    await _index(db, doc)

    hits = await retrieve(
        session=db,
        actor=other,
        query="findings shared explicitly",
        top_k=5,
    )
    assert any(h.source_item_id == str(doc.id) for h in hits)


@pytest.mark.asyncio
async def test_demo_docs_isolated_from_non_demo_search(db: Session) -> None:
    owner = create_random_user(db)
    doc = V2Document(
        owner_id=owner.id,
        title="Demo Doc",
        is_demo=True,
        human_summary="demo only chunk content",
        details_markdown_sections=[
            {"anchor_id": "demo", "markdown": "demo only chunk content"}
        ],
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    await _index(db, doc)

    # Searching the demo corpus finds it.
    demo_hits = await retrieve(
        session=db,
        actor=owner,
        query="demo only chunk content",
        top_k=5,
        demo=True,
    )
    assert any(h.source_item_id == str(doc.id) for h in demo_hits)

    # Searching real corpus does NOT.
    real_hits = await retrieve(
        session=db,
        actor=owner,
        query="demo only chunk content",
        top_k=5,
        demo=False,
    )
    assert all(h.source_item_id != str(doc.id) for h in real_hits)


@pytest.fixture(autouse=True)
def _cleanup(db: Session):
    yield
    # Remove embeddings + documents created in the test session so the
    # next test starts with a clean corpus.
    from sqlalchemy import delete  # local import to avoid linter noise

    db.execute(delete(SourceItemEmbedding))
    db.execute(delete(V2DocumentShare))
    db.execute(delete(V2Document))
    db.commit()
