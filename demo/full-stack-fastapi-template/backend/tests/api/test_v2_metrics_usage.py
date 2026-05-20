"""POST /v2/metrics/usage — the harness-hook ingest endpoint.

Confirms that fire-and-forget usage payloads land as ``tokens.consumed``
rows that the existing Metrics read API can attribute back to the
calling user. No document required, no MCP session required."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    METRICS_EVENT_TOKENS_CONSUMED,
    MetricsEvent,
)
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import random_email

API = settings.API_V1_STR


def _auth(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(client=client, email=random_email(), db=db)


def test_post_usage_records_tokens_consumed(
    client: TestClient, db: Session
) -> None:
    headers = _auth(client, db)
    resp = client.post(
        f"{API}/v2/metrics/usage",
        headers=headers,
        params={"source": "hook"},
        json={
            "model_id": "claude-opus-4-7",
            "input_tokens": 1234,
            "output_tokens": 567,
            "cache_read_input_tokens": 89,
            "cache_creation_input_tokens": 0,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == METRICS_EVENT_TOKENS_CONSUMED
    assert body["input_tokens"] == 1234
    assert body["output_tokens"] == 567
    assert body["cache_read_tokens"] == 89
    # claude-opus-4-7 is seeded in model_pricing → USD amount populates.
    assert body["usd_amount"] is not None


def test_post_usage_billed_to_label_lands_in_payload(
    client: TestClient, db: Session
) -> None:
    headers = _auth(client, db)
    resp = client.post(
        f"{API}/v2/metrics/usage",
        headers=headers,
        params={"source": "search"},
        json={"model_id": "claude-sonnet-4-6", "input_tokens": 10, "output_tokens": 5},
    )
    assert resp.status_code == 201
    event_id = resp.json()["id"]
    row = db.exec(
        select(MetricsEvent).where(MetricsEvent.id == event_id)
    ).one()
    assert row.payload.get("source") == "search"
    assert row.payload.get("billed_to") == "search"


def test_post_usage_unknown_model_still_records(
    client: TestClient, db: Session
) -> None:
    """If pricing isn't seeded for this model_id, tokens still record
    (usd_amount is null). The endpoint must not 500 just because the
    pricing snapshot is incomplete."""

    headers = _auth(client, db)
    resp = client.post(
        f"{API}/v2/metrics/usage",
        headers=headers,
        json={"model_id": "gpt-4o-mini", "input_tokens": 100, "output_tokens": 50},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["model_id"] == "gpt-4o-mini"
    assert body["input_tokens"] == 100
    assert body["usd_amount"] is None


def test_post_usage_requires_auth(client: TestClient) -> None:
    resp = client.post(
        f"{API}/v2/metrics/usage",
        json={"model_id": "claude-opus-4-7", "input_tokens": 1, "output_tokens": 1},
    )
    assert resp.status_code in (401, 403)
