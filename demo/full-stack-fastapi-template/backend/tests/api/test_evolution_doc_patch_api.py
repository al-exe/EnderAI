from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.taskforce.evolution_doc_patch import apply_evolution_patch
from app.core.taskforce.evolution_summary import StoredEvolutionSummary
from app.core.taskforce.summarizer import SummarizerResult
from app.models import V2DocumentEvolutionChangelog
from tests.api.test_organizations_api import _signup
from tests.core.taskforce.test_evolution_doc_synthesis import _archive, _library_doc


def test_revert_evolution_changelog_route(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup(client, db, full_name="Evolution Revert User")
    actor = crud.get_user_by_email(session=db, email=email)
    assert actor is not None

    document = _library_doc(
        db,
        actor,
        title="API revert target",
        body="Stable baseline content",
    )
    archive = _archive(
        db,
        actor,
        summary_points=["Append this through evolution patch"],
    )
    stored = StoredEvolutionSummary(
        summary_points=["Append this through evolution patch"],
        details_sections=[],
        decisions=[],
        outcome=None,
        materiality_score=1.0,
    )
    summary = SummarizerResult(
        materiality_score=1.0,
        summary_points=stored.summary_points,
        details_sections=[],
        files_touched=[],
        commands_of_interest=[],
        decisions=[],
        outcome=None,
        open_questions=[],
    )
    changelog = apply_evolution_patch(
        db,
        actor=actor,
        document=document,
        archive=archive,
        stored=stored,
        summary=summary,
        match_score=0.88,
    )
    assert changelog is not None
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/v2/documents/{document.id}/evolution-changelog/{changelog.id}/revert",
        headers=headers,
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    row = db.get(V2DocumentEvolutionChangelog, changelog.id)
    assert row is not None
    assert row.reverted_at is not None
