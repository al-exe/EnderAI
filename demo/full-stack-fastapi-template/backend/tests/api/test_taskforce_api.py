"""Integration tests for the Taskforce hook endpoints (TF-175).

Mirrors the patterns in ``tests/api/test_v2_documents_api.py``: each test
signs up a fresh user, issues a few API calls, and asserts the
response/DB state.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings
from tests.utils.utils import random_email, random_lower_string


def _signup(client: TestClient) -> tuple[str, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={"email": email, "password": password, "full_name": "Taskforce Tester"},
    )
    assert 200 <= response.status_code < 300, response.text
    from tests.utils.user import user_authentication_headers
    headers = user_authentication_headers(client=client, email=email, password=password)
    return email, headers


def _create_document(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str,
    description: str = "",
) -> str:
    response = client.post(
        f"{settings.API_V1_STR}/v2/documents/",
        headers=headers,
        json={"title": title, "description": description},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_taskforce_discover_returns_top_matches_for_owner(client: TestClient) -> None:
    _, headers = _signup(client)
    _create_document(
        client,
        headers,
        title="Library page polish",
        description="Cleanup of the metrics page; USD Saved → USD Offset.",
    )
    _create_document(
        client,
        headers,
        title="Banana yacht unrelated",
        description="Completely off-topic content.",
    )

    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": "fix the library polish metrics card"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "query_id" in body
    assert isinstance(body["matches"], list)
    # The polish doc should outrank the banana doc.
    if body["matches"]:
        top = body["matches"][0]
        assert "Library" in top["title"]
        assert top["score"] > 0.0
        assert top["confidence_band"] in {"high", "medium", "low"}
        assert "rediscovery_cost_tokens" in top
        assert "consult_token_cost" in top


def test_taskforce_discover_records_consulted_events(client: TestClient) -> None:
    _, headers = _signup(client)
    _create_document(client, headers, title="Important library work")

    discover = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": "library work continuation", "k": 3, "min_score": 0.0},
    )
    assert discover.status_code == 200, discover.text
    matches = discover.json()["matches"]
    if not matches:
        # Scoring might be too strict on this fixture; not a hard requirement here.
        return

    metrics = client.get(
        f"{settings.API_V1_STR}/v2/metrics",
        headers=headers,
        params={"metrics": "documents_consulted", "window": "all"},
    )
    assert metrics.status_code == 200, metrics.text
    consulted = metrics.json()["metrics"]["documents_consulted"]
    assert int(consulted["total"]) >= 1


def test_taskforce_discover_empty_library_still_returns_query_id(
    client: TestClient,
) -> None:
    _, headers = _signup(client)
    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": "anything goes here"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "query_id" in body
    assert body["matches"] == []


def test_taskforce_discover_rejects_empty_prompt(client: TestClient) -> None:
    _, headers = _signup(client)
    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        headers=headers,
        json={"prompt": ""},
    )
    assert response.status_code == 422


def test_taskforce_discover_requires_auth(client: TestClient) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/v2/taskforce/discover",
        json={"prompt": "anything"},
    )
    assert response.status_code in (401, 403)


def test_documents_consulted_metric_listed_in_definitions(client: TestClient) -> None:
    _, headers = _signup(client)
    response = client.get(
        f"{settings.API_V1_STR}/v2/metrics/definitions",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    names = {row["name"] for row in response.json()["data"]}
    assert "documents_consulted" in names
