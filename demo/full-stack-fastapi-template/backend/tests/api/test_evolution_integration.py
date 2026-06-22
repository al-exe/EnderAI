from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.taskforce.evolution import EVOLUTION_PENDING_KEY
from app.models import TaskforceSessionArchive
from tests.api.test_taskforce_api import _signup


def test_observe_does_not_run_evolve_session_inline(
    client: TestClient,
    monkeypatch,
) -> None:
    """Evolution must stay off the observe request path (T0 acceptance)."""

    _, headers = _signup(client)
    with patch("app.core.taskforce.evolution.evolve_session") as evolve:
        response = client.post(
            f"{settings.API_V1_STR}/v2/taskforce/observe",
            headers=headers,
            json={
                "kind": "final",
                "prompt": "Ship the offline evolution orchestrator",
                "transcript": [
                    {"role": "user", "content": "do work"},
                    {"role": "assistant", "content": "done"},
                ],
                "session_id": "evolution-inline-guard",
                "files_touched": ["app/core/taskforce/evolution.py"],
                "duration_ms": 1000,
            },
        )
        evolve.assert_not_called()

    assert response.status_code == 202, response.text
    assert response.json()["action"] == "created"


def test_material_observe_flags_session_for_offline_evolution(
    client: TestClient, db: Session
) -> None:
    _, headers = _signup(client)
    session_id = "evolution-pending-flag"
    summary_point = "Flag me for offline evolution with summary snapshot"

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "final",
            "prompt": "Flag me for offline evolution",
            "transcript": [
                {"role": "user", "content": "work"},
                {"role": "assistant", "content": "done"},
            ],
            "session_id": session_id,
            "files_touched": ["app/core/taskforce/evolution.py"],
            "duration_ms": 1000,
            "summary_points": [summary_point],
        },
    )
    assert response.status_code == 202, response.text

    archive = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.session_id == session_id
        )
    ).first()
    assert archive is not None
    assert archive.source_metadata.get(EVOLUTION_PENDING_KEY) is True
    stored = archive.source_metadata.get("evolution_summary") or {}
    assert summary_point in (stored.get("summary_points") or [])


def test_skipped_observe_does_not_flag_evolution(client: TestClient, db: Session) -> None:
    """Non-material sessions should not enqueue offline evolution."""

    _, headers = _signup(client)
    session_id = "evolution-skipped"

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/observe",
        headers=headers,
        json={
            "kind": "checkpoint",
            "prompt": "",
            "transcript": [],
            "session_id": session_id,
            "duration_ms": 0,
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["action"] == "skipped"

    archive = db.exec(
        select(TaskforceSessionArchive).where(
            TaskforceSessionArchive.session_id == session_id
        )
    ).first()
    if archive is not None:
        assert archive.source_metadata.get(EVOLUTION_PENDING_KEY) is not True
