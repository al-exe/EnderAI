"""TF-218 — session-archive backfill from metrics_event.

``backfill_session_archives`` creates best-effort archive rows for old sessions
that exist only as ``metrics_event`` rows (e.g. produced by ``session/start``,
which records a consult event but never observes). Verifies it's a real dry-run,
writes a readable title + provenance, stays org/demo scoped, and is idempotent.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app.core.taskforce.archive import backfill_session_archives
from app.models import TaskforceSessionArchive, TaskforceSessionEvent
from tests.api.test_taskforce_ledger import _alice_doc_bob_reuse


def _archive_count(db: Session, org_id) -> int:
    return len(
        db.exec(
            select(TaskforceSessionArchive).where(
                TaskforceSessionArchive.organization_id == org_id
            )
        ).all()
    )


def _remove_session_read_models(db: Session, org_id) -> None:
    db.exec(
        delete(TaskforceSessionEvent).where(
            TaskforceSessionEvent.organization_id == org_id
        )
    )
    db.exec(
        delete(TaskforceSessionArchive).where(
            TaskforceSessionArchive.organization_id == org_id
        )
    )
    db.commit()


def test_backfill_dry_run_writes_nothing(client: TestClient, db: Session) -> None:
    _, _, bob_email, _, _ = _alice_doc_bob_reuse(client, db)
    from tests.api.test_taskforce_api import _user_by_email

    org_id = _user_by_email(db, bob_email).organization_id
    _remove_session_read_models(db, org_id)
    before = _archive_count(db, org_id)

    report = backfill_session_archives(db, organization_id=org_id, dry_run=True)

    assert report.sessions_seen >= 1
    assert report.archives_created >= 1
    assert _archive_count(db, org_id) == before  # nothing persisted


def test_backfill_creates_archive_with_title_and_provenance(
    client: TestClient, db: Session
) -> None:
    from tests.api.test_taskforce_api import _user_by_email

    _, _, bob_email, _, _ = _alice_doc_bob_reuse(client, db)
    org_id = _user_by_email(db, bob_email).organization_id
    _remove_session_read_models(db, org_id)

    report = backfill_session_archives(db, organization_id=org_id, dry_run=False)
    db.commit()

    assert report.archives_created >= 1
    archives = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.organization_id == org_id
        )
    ).all()
    assert archives
    a = archives[0]
    assert a.title  # readable title backfilled from the metrics prompt
    assert a.client == "claude-code"  # provenance carried from payload
    assert a.started_at is not None and a.ended_at is not None
    assert a.source_metadata.get("backfilled") is True
    assert db.exec(
        select(TaskforceSessionEvent).where(
            TaskforceSessionEvent.session_id == a.session_id
        )
    ).all() == []


def test_backfill_is_idempotent(client: TestClient, db: Session) -> None:
    from tests.api.test_taskforce_api import _user_by_email

    _, _, bob_email, _, _ = _alice_doc_bob_reuse(client, db)
    org_id = _user_by_email(db, bob_email).organization_id
    _remove_session_read_models(db, org_id)

    first = backfill_session_archives(db, organization_id=org_id, dry_run=False)
    db.commit()
    count_after_first = _archive_count(db, org_id)

    second = backfill_session_archives(db, organization_id=org_id, dry_run=False)
    db.commit()

    assert second.archives_created == 0
    assert second.skipped_existing >= first.archives_created
    assert _archive_count(db, org_id) == count_after_first  # no duplicates


def test_backfill_scopes_to_org(client: TestClient, db: Session) -> None:
    from tests.api.test_taskforce_api import _signup, _user_by_email

    _, _, bob_email, _, _ = _alice_doc_bob_reuse(client, db)
    org_id = _user_by_email(db, bob_email).organization_id
    _remove_session_read_models(db, org_id)

    # An unrelated solo user with their own session in a different org.
    _outsider_email, outsider_headers = _signup(client)
    client.post(
        "/api/v1/v2/taskforce/session/start",
        headers=outsider_headers,
        json={"prompt": "unrelated work", "client": "codex", "min_score": 0.0},
    )

    report = backfill_session_archives(db, organization_id=org_id, dry_run=False)
    db.commit()

    # Only the target org's sessions were archived.
    archives = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.organization_id == org_id
        )
    ).all()
    assert report.archives_created == len(archives)
    assert all(a.organization_id == org_id for a in archives)
