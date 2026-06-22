from __future__ import annotations

import uuid
from unittest.mock import patch

from sqlmodel import Session

from app.core.config import settings
from app.core.taskforce.evolution import (
    EVOLUTION_PENDING_KEY,
    evolve_session,
    mark_session_for_evolution,
    sweep_pending_once,
)
from app.core.taskforce.evolution_gate import can_auto_evolve
from app.models import Organization, TaskforceSessionArchive, User
from tests.utils.user import create_random_user
from tests.utils.utils import random_lower_string


def _org(db: Session, *, auto_evolve_enabled: bool = True) -> Organization:
    org = Organization(
        name=f"Evolution {random_lower_string()}",
        auto_evolve_enabled=auto_evolve_enabled,
    )
    db.add(org)
    db.flush()
    return org


def _user(db: Session, org: Organization) -> User:
    user = create_random_user(db)
    user.organization_id = org.id
    user.organization_role = "admin"
    db.add(user)
    db.flush()
    return user


def _archive(
    db: Session,
    user: User,
    *,
    pending: bool = True,
) -> TaskforceSessionArchive:
    archive = TaskforceSessionArchive(
        session_id=f"evolve-{random_lower_string()}",
        actor_id=user.id,
        organization_id=user.organization_id,
        is_demo=False,
        source_metadata={EVOLUTION_PENDING_KEY: pending} if pending else {},
    )
    db.add(archive)
    db.flush()
    return archive


def test_can_auto_evolve_blocks_when_env_disabled(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "TF_SELF_EVOLVE", False)
    org = _org(db)
    result = can_auto_evolve(db, organization_id=org.id)
    assert result.allowed is False
    assert result.reason == "disabled_env"


def test_can_auto_evolve_blocks_when_org_switch_off(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "TF_SELF_EVOLVE", True)
    org = _org(db, auto_evolve_enabled=False)
    result = can_auto_evolve(db, organization_id=org.id)
    assert result.allowed is False
    assert result.reason == "disabled_org"


def test_can_auto_evolve_allows_when_enabled(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "TF_SELF_EVOLVE", True)
    org = _org(db, auto_evolve_enabled=True)
    result = can_auto_evolve(db, organization_id=org.id)
    assert result.allowed is True
    assert result.reason is None


def test_evolve_session_skips_when_org_switch_off(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "TF_SELF_EVOLVE", True)
    org = _org(db, auto_evolve_enabled=False)
    user = _user(db, org)
    archive = _archive(db, user)

    with patch("app.core.taskforce.evolution.compound_specialists") as compound:
        result = evolve_session(db, archive)
        compound.assert_not_called()

    assert result.skipped is True
    assert result.skip_reason == "disabled_org"


def test_evolve_session_runs_compounding_when_allowed(
    db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "TF_SELF_EVOLVE", True)
    org = _org(db, auto_evolve_enabled=True)
    user = _user(db, org)
    archive = _archive(db, user)

    with patch(
        "app.core.taskforce.evolution.compound_specialists",
        return_value={"specialists_seen": 0, "links_created": 0},
    ) as compound:
        result = evolve_session(db, archive)
        compound.assert_called_once_with(
            db,
            organization_id=org.id,
            dry_run=False,
        )

    assert result.skipped is False
    assert archive.source_metadata.get(EVOLUTION_PENDING_KEY) is False
    assert archive.source_metadata.get("evolution_processed_at")


def test_sweep_pending_once_respects_env_flag(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "TF_SELF_EVOLVE", False)
    org = _org(db)
    user = _user(db, org)
    _archive(db, user, pending=True)

    report = sweep_pending_once(db)
    assert report.processed == 0
    assert report.skipped == 0


def test_sweep_pending_once_processes_flagged_archives(
    db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "TF_SELF_EVOLVE", True)
    org = _org(db)
    user = _user(db, org)
    archive = _archive(db, user, pending=True)

    with patch(
        "app.core.taskforce.evolution.compound_specialists",
        return_value={"specialists_seen": 0},
    ):
        report = sweep_pending_once(db)

    assert report.processed >= 1
    db.refresh(archive)
    assert archive.source_metadata.get(EVOLUTION_PENDING_KEY) is False


def test_sweep_pending_once_isolates_poison_archive(
    db: Session, monkeypatch
) -> None:
    """A single failing archive must be finalized + skipped, not wedge the sweep."""
    monkeypatch.setattr(settings, "TF_SELF_EVOLVE", True)
    org = _org(db)
    user = _user(db, org)
    poison = _archive(db, user, pending=True)
    healthy = _archive(db, user, pending=True)

    def _synth(session, *, archive):
        if archive.session_id == poison.session_id:
            raise RuntimeError("boom")
        return ([], [])

    with patch(
        "app.core.taskforce.evolution.synthesize_documents", side_effect=_synth
    ), patch(
        "app.core.taskforce.evolution.compound_specialists",
        return_value={"specialists_seen": 0},
    ):
        report = sweep_pending_once(db)

    assert report.errored == 1
    assert report.processed == 1
    db.refresh(poison)
    db.refresh(healthy)
    # Poison archive finalized with an error reason → not retried forever.
    assert poison.source_metadata.get(EVOLUTION_PENDING_KEY) is False
    assert "evolution_error" in poison.source_metadata
    # Healthy archive still processed despite the poison.
    assert healthy.source_metadata.get(EVOLUTION_PENDING_KEY) is False


def test_mark_session_for_evolution_sets_metadata() -> None:
    archive = TaskforceSessionArchive(
        session_id="mark-test",
        actor_id=uuid.uuid4(),
        is_demo=False,
    )
    mark_session_for_evolution(archive)
    assert archive.source_metadata[EVOLUTION_PENDING_KEY] is True
