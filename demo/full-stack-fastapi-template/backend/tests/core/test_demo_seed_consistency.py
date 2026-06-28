"""Guards the slug coupling across the V2 demo seed catalogs.

The demo data is authored across several files that reference each other by
slug: document titles (``DOCUMENT_SLUG_TITLES``) join the document catalog
(``iter_demo_seed_catalog``) to the specialist links, the Alex invocation
fixtures, and the metrics session specs. If any of those reference a slug that
no longer exists in the catalog, the seed silently drops links/sessions. This
test fails loudly instead so the catalogs can only be trimmed or extended in
lockstep.
"""

from __future__ import annotations

from app.core.agents.seed import (
    ALEX_DEMO_INVOCATIONS,
    DOCUMENT_SLUG_TITLES,
    SEEDED_SPECIALISTS,
    SPECIALIST_DOCUMENT_LINKS,
    _build_metrics_session_specs,
)
from app.core.v2_documents import iter_demo_seed_catalog


def _valid_doc_slugs() -> set[str]:
    return set(DOCUMENT_SLUG_TITLES.keys())


def _valid_specialist_slugs() -> set[str]:
    return {spec["slug"] for spec in SEEDED_SPECIALISTS}


def test_slug_titles_resolve_to_catalog_documents() -> None:
    catalog_titles = {seed["title"] for seed in iter_demo_seed_catalog()}
    missing = {
        slug: title
        for slug, title in DOCUMENT_SLUG_TITLES.items()
        if title not in catalog_titles
    }
    assert not missing, f"DOCUMENT_SLUG_TITLES point at unknown documents: {missing}"


def test_specialist_slugs_are_unique() -> None:
    slugs = [spec["slug"] for spec in SEEDED_SPECIALISTS]
    duplicates = {slug for slug in slugs if slugs.count(slug) > 1}
    assert not duplicates, f"duplicate specialist slugs: {duplicates}"


def test_specialist_document_links_reference_known_slugs() -> None:
    doc_slugs = _valid_doc_slugs()
    specialist_slugs = _valid_specialist_slugs()
    for specialist_slug, links in SPECIALIST_DOCUMENT_LINKS.items():
        assert specialist_slug in specialist_slugs, (
            f"link references unknown specialist: {specialist_slug}"
        )
        for doc_slug, _anchor_id, _reason in links:
            assert doc_slug in doc_slugs, (
                f"{specialist_slug} links unknown document slug: {doc_slug}"
            )


def test_invocations_reference_known_slugs() -> None:
    doc_slugs = _valid_doc_slugs()
    specialist_slugs = _valid_specialist_slugs()
    for invocation in ALEX_DEMO_INVOCATIONS:
        assert invocation["specialist_slug"] in specialist_slugs, (
            f"invocation references unknown specialist: {invocation['specialist_slug']}"
        )
        for doc_slug in invocation.get("documents", []):
            assert doc_slug in doc_slugs, (
                f"invocation references unknown document slug: {doc_slug}"
            )


def test_metrics_session_specs_reference_known_slugs() -> None:
    doc_slugs = _valid_doc_slugs()
    specialist_slugs = _valid_specialist_slugs()
    for spec in _build_metrics_session_specs():
        assert spec["specialist_slug"] in specialist_slugs, (
            f"session spec references unknown specialist: {spec['specialist_slug']}"
        )
        anchor_slug = spec.get("anchor_slug")
        if anchor_slug is not None:
            assert anchor_slug in doc_slugs, (
                f"session spec anchor_slug unknown: {anchor_slug}"
            )
        for consultation in spec.get("consultations") or []:
            assert consultation["slug"] in doc_slugs, (
                f"session spec consults unknown document slug: {consultation['slug']}"
            )
