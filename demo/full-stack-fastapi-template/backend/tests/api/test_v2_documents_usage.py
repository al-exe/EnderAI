from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    METRICS_EVENT_DOCUMENT_CREATED,
    METRICS_EVENT_DOCUMENT_UPDATED,
    METRICS_EVENT_TOKENS_CONSUMED,
    METRICS_EVENT_TOKENS_SAVED_CACHE,
    MetricsEvent,
)
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import random_email


def _make_authenticated_user(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(client=client, email=random_email(), db=db)


def _create_doc(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        f"{settings.API_V1_STR}/v2/documents/",
        headers=headers,
        json={
            "title": "Usage Test Doc",
            "main_body": [{"segments": [{"text": "summary content"}]}],
            "details_markdown_sections": [
                {"anchor_id": "req", "markdown": "x" * 4_000}
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_post_create_records_document_created_event(
    client: TestClient, db: Session
) -> None:
    headers = _make_authenticated_user(client, db)
    document_id = _create_doc(client, headers)

    events = list(
        db.exec(select(MetricsEvent).where(MetricsEvent.document_id == document_id))
    )
    kinds = {e.kind for e in events}
    assert METRICS_EVENT_DOCUMENT_CREATED in kinds


def test_patch_with_usage_records_consumed_event(
    client: TestClient, db: Session
) -> None:
    headers = _make_authenticated_user(client, db)
    document_id = _create_doc(client, headers)

    response = client.patch(
        f"{settings.API_V1_STR}/v2/documents/{document_id}",
        headers=headers,
        json={
            "description": "after",
            "usage": {
                "model_id": "claude-opus-4-7",
                "input_tokens": 1000,
                "output_tokens": 200,
            },
        },
    )
    assert response.status_code == 200, response.text

    events = list(
        db.exec(select(MetricsEvent).where(MetricsEvent.document_id == document_id))
    )
    kinds = {e.kind for e in events}
    assert METRICS_EVENT_DOCUMENT_UPDATED in kinds
    assert METRICS_EVENT_TOKENS_CONSUMED in kinds


def test_post_usage_endpoint_returns_event_envelope(
    client: TestClient, db: Session
) -> None:
    headers = _make_authenticated_user(client, db)
    document_id = _create_doc(client, headers)

    response = client.post(
        f"{settings.API_V1_STR}/v2/documents/{document_id}/usage",
        headers=headers,
        json={
            "model_id": "claude-opus-4-7",
            "input_tokens": 500,
            "output_tokens": 100,
            "cache_read_input_tokens": 1_000_000,
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert "events" in body
    kinds = {e["kind"] for e in body["events"]}
    assert METRICS_EVENT_TOKENS_CONSUMED in kinds
    assert METRICS_EVENT_TOKENS_SAVED_CACHE in kinds


def test_post_usage_endpoint_requires_owner_access(
    client: TestClient, db: Session
) -> None:
    owner_headers = _make_authenticated_user(client, db)
    document_id = _create_doc(client, owner_headers)

    other_headers = _make_authenticated_user(client, db)
    response = client.post(
        f"{settings.API_V1_STR}/v2/documents/{document_id}/usage",
        headers=other_headers,
        json={"model_id": "claude-opus-4-7", "input_tokens": 10},
    )
    assert response.status_code == 404, response.text
