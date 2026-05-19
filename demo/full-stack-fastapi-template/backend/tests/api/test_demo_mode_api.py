from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import UserCreate
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _signup_and_login(client: TestClient) -> tuple[str, dict[str, str]]:
    email = random_email()
    password = random_lower_string()

    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={
            "email": email,
            "password": password,
            "full_name": "Demo Mode Tester",
        },
    )
    assert 200 <= response.status_code < 300, response.text

    headers = user_authentication_headers(
        client=client,
        email=email,
        password=password,
    )
    return email, headers


def test_demo_mode_routes_filter_live_and_demo_workspaces(
    client: TestClient,
    db: Session,
) -> None:
    email, headers = _signup_and_login(client)
    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    assert user.demo_seeded_at is not None

    empty_live_topics = client.get("/api/v1/topics/", headers=headers)
    assert empty_live_topics.status_code == 200, empty_live_topics.text
    assert empty_live_topics.json()["count"] == 0

    live_topic = client.post(
        "/api/v1/topics/",
        headers=headers,
        json={
            "title": "Live workspace topic",
            "workflow_key": f"live_workspace_topic_{random_lower_string()[:8]}",
            "description": "This topic should only appear outside demo mode.",
            "aliases": ["live mode"],
        },
    )
    assert live_topic.status_code == 201, live_topic.text
    live_topic_id = live_topic.json()["id"]

    live_case = client.post(
        "/api/v1/cases/",
        headers=headers,
        json={
            "topic_id": live_topic_id,
            "title": "Live workspace case",
            "status": "done",
            "summary_current": "Only the real workspace should show this case.",
            "files": ["backend/app/live.py"],
            "symbols": ["live_workspace_case"],
            "errors": ["live-only regression"],
            "outcome": "Live mode behavior remained isolated from demo mode.",
        },
    )
    assert live_case.status_code == 201, live_case.text
    live_case_id = live_case.json()["id"]

    live_topics = client.get("/api/v1/topics/", headers=headers)
    assert live_topics.status_code == 200, live_topics.text
    live_topics_body = live_topics.json()
    assert live_topics_body["count"] == 1
    assert [row["id"] for row in live_topics_body["data"]] == [live_topic_id]

    demo_topics = client.get(
        "/api/v1/topics/",
        headers=headers,
        params={"demo": True},
    )
    assert demo_topics.status_code == 200, demo_topics.text
    demo_topics_body = demo_topics.json()
    assert demo_topics_body["count"] >= 7
    assert all(row["id"] != live_topic_id for row in demo_topics_body["data"])
    demo_topic_id = demo_topics_body["data"][0]["id"]

    hidden_demo_topic = client.get(f"/api/v1/topics/{demo_topic_id}", headers=headers)
    assert hidden_demo_topic.status_code == 404, hidden_demo_topic.text

    visible_demo_topic = client.get(
        f"/api/v1/topics/{demo_topic_id}",
        headers=headers,
        params={"demo": True},
    )
    assert visible_demo_topic.status_code == 200, visible_demo_topic.text

    live_cases = client.get("/api/v1/cases/", headers=headers)
    assert live_cases.status_code == 200, live_cases.text
    live_cases_body = live_cases.json()
    assert live_cases_body["count"] == 1
    assert [row["id"] for row in live_cases_body["data"]] == [live_case_id]

    demo_cases = client.get(
        "/api/v1/cases/",
        headers=headers,
        params={"demo": True},
    )
    assert demo_cases.status_code == 200, demo_cases.text
    demo_cases_body = demo_cases.json()
    assert demo_cases_body["count"] >= 1
    assert all(row["id"] != live_case_id for row in demo_cases_body["data"])

    live_search = client.get(
        "/api/v1/search/",
        headers=headers,
        params={"q": "pgbouncer"},
    )
    assert live_search.status_code == 200, live_search.text
    assert live_search.json()["topic_count"] == 0
    assert live_search.json()["case_count"] == 0

    demo_search = client.get(
        "/api/v1/search/",
        headers=headers,
        params={"q": "pgbouncer", "demo": True},
    )
    assert demo_search.status_code == 200, demo_search.text
    demo_search_body = demo_search.json()
    assert demo_search_body["topic_count"] + demo_search_body["case_count"] >= 1

    match_payload = {
        "title": "Pgbouncer saturation after autoscaling",
        "request_summary": "Worker autoscaling exhausted pooled Postgres connections.",
        "errors": ["remaining connection slots are reserved"],
        "contexts": ["pgbouncer transaction pools"],
    }
    live_match = client.post(
        "/api/v1/topics/match",
        headers=headers,
        json=match_payload,
    )
    assert live_match.status_code == 200, live_match.text
    live_match_body = live_match.json()
    assert all(
        candidate["topic"]["id"] == live_topic_id
        for candidate in live_match_body["candidates"]
    )

    demo_match = client.post(
        "/api/v1/topics/match",
        headers=headers,
        params={"demo": True},
        json=match_payload,
    )
    assert demo_match.status_code == 200, demo_match.text
    demo_match_body = demo_match.json()
    assert len(demo_match_body["candidates"]) >= 1
    assert all(
        candidate["topic"]["id"] != live_topic_id
        for candidate in demo_match_body["candidates"]
    )

    live_pack = client.post(
        "/api/v1/context-packs/build",
        headers=headers,
        json={
            **match_payload,
            "max_topics": 1,
            "max_cases_per_topic": 2,
        },
    )
    assert live_pack.status_code == 200, live_pack.text
    live_pack_body = live_pack.json()
    assert all(
        topic_id == live_topic_id for topic_id in live_pack_body["selected_topic_ids"]
    )
    assert all(
        case_id == live_case_id for case_id in live_pack_body["selected_case_ids"]
    )

    demo_pack = client.post(
        "/api/v1/context-packs/build",
        headers=headers,
        params={"demo": True},
        json={
            **match_payload,
            "max_topics": 1,
            "max_cases_per_topic": 2,
        },
    )
    assert demo_pack.status_code == 200, demo_pack.text
    demo_pack_body = demo_pack.json()
    assert len(demo_pack_body["selected_topic_ids"]) >= 1
    assert len(demo_pack_body["selected_case_ids"]) >= 1
    assert live_topic_id not in demo_pack_body["selected_topic_ids"]
    assert live_case_id not in demo_pack_body["selected_case_ids"]


def test_demo_mode_lazily_seeds_existing_users(
    client: TestClient,
    db: Session,
) -> None:
    email = random_email()
    password = random_lower_string()
    crud.create_user(
        session=db,
        user_create=UserCreate(email=email, password=password),
    )
    headers = user_authentication_headers(
        client=client,
        email=email,
        password=password,
    )

    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    assert user.demo_seeded_at is None

    response = client.get(
        "/api/v1/topics/",
        headers=headers,
        params={"demo": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["count"] >= 7

    db.refresh(user)
    assert user.demo_seeded_at is not None
