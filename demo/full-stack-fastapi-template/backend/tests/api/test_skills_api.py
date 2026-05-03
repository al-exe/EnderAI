import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import Skill
from tests.utils.utils import random_email, random_lower_string


def test_generate_match_and_use_skill(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    topic_res = client.post(
        f"{settings.API_V1_STR}/topics/",
        headers=normal_user_token_headers,
        json={
            "title": "Hosted MCP OAuth Rotation",
            "workflow_key": "hosted_mcp_oauth_rotation",
            "description": "Recover agent auth after provider-side token rotation.",
            "aliases": ["oauth", "hosted mcp", "token rotation"],
        },
    )
    assert topic_res.status_code == 201, topic_res.text
    topic_id = topic_res.json()["id"]

    case_res = client.post(
        f"{settings.API_V1_STR}/cases/",
        headers=normal_user_token_headers,
        json={
            "topic_id": topic_id,
            "title": "Refresh token revoked during key rollover",
            "status": "done",
            "input_summary": "Hosted MCP refresh failed with invalid_grant.",
            "summary_current": "The client retried a revoked refresh token instead of forcing relogin.",
            "files": ["mcp/enderai-api-mcp/src/sessionAuth.ts"],
            "symbols": ["refreshHostedSession"],
            "errors": ["invalid_grant"],
            "symptoms": ["hosted agents failed after key rollover"],
            "hypotheses": [
                {
                    "statement": "Revoked refresh tokens need a relogin path.",
                    "status": "supported",
                }
            ],
            "outcome": "Hosted agents recover by clearing cached credentials and surfacing relogin guidance.",
        },
    )
    assert case_res.status_code == 201, case_res.text
    case_id = case_res.json()["id"]

    generate_res = client.post(
        f"{settings.API_V1_STR}/skills/generate",
        headers=normal_user_token_headers,
        json={"topic_id": topic_id},
    )
    assert generate_res.status_code == 201, generate_res.text
    skill = generate_res.json()
    skill_id = skill["id"]
    assert skill["source_topic_id"] == topic_id
    assert case_id in skill["source_case_ids"]
    assert "Skill guidance is advisory" in skill["instructions_md"]
    assert "Hosted MCP OAuth Rotation" in skill["instructions_md"]

    list_res = client.get(
        f"{settings.API_V1_STR}/skills/",
        headers=normal_user_token_headers,
        params={"q": "oauth"},
    )
    assert list_res.status_code == 200, list_res.text
    assert list_res.json()["count"] >= 1
    assert any(row["id"] == skill_id for row in list_res.json()["data"])

    match_res = client.post(
        f"{settings.API_V1_STR}/skills/match",
        headers=normal_user_token_headers,
        json={
            "request_summary": "Hosted MCP returns invalid_grant after OAuth key rollover.",
            "files": ["mcp/enderai-api-mcp/src/sessionAuth.ts"],
            "symbols": ["refreshHostedSession"],
            "errors": ["invalid_grant"],
        },
    )
    assert match_res.status_code == 200, match_res.text
    match_body = match_res.json()
    assert match_body["candidates"][0]["skill"]["id"] == skill_id
    assert match_body["candidates"][0]["confidence"] in {"high", "medium"}

    use_res = client.post(
        f"{settings.API_V1_STR}/skills/use",
        headers=normal_user_token_headers,
        json={"case_id": case_id},
    )
    assert use_res.status_code == 200, use_res.text
    use_body = use_res.json()
    assert use_body["selected_skill"]["id"] == skill_id
    assert use_body["selected_skill"]["usage_count"] == 1
    assert use_body["instructions_md"] == skill["instructions_md"]
    assert use_body["agent_usage_note"].startswith("Use the returned skill")

    refresh_res = client.post(
        f"{settings.API_V1_STR}/skills/{skill_id}/refresh",
        headers=normal_user_token_headers,
    )
    assert refresh_res.status_code == 200, refresh_res.text
    assert refresh_res.json()["id"] == skill_id


def test_inactive_user_can_read_and_use_demo_skills_but_cannot_generate(
    client: TestClient,
    db: Session,
) -> None:
    email = random_email()
    password = random_lower_string()
    signup_res = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={"email": email, "password": password, "full_name": "Pending Skill User"},
    )
    assert signup_res.status_code == 200, signup_res.text

    login_res = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": password},
    )
    assert login_res.status_code == 200, login_res.text
    headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

    topics_res = client.get(
        f"{settings.API_V1_STR}/topics/",
        headers=headers,
        params={"demo": True},
    )
    assert topics_res.status_code == 200, topics_res.text
    topic_id = topics_res.json()["data"][0]["id"]

    skills_res = client.get(
        f"{settings.API_V1_STR}/skills/",
        headers=headers,
        params={"demo": True},
    )
    assert skills_res.status_code == 200, skills_res.text
    assert skills_res.json()["count"] >= 1
    skill_id = skills_res.json()["data"][0]["id"]

    generate_res = client.post(
        f"{settings.API_V1_STR}/skills/generate",
        headers=headers,
        params={"demo": True},
        json={"topic_id": topic_id},
    )
    assert generate_res.status_code == 403
    assert generate_res.json() == {"detail": "Inactive users cannot write data"}

    use_res = client.post(
        f"{settings.API_V1_STR}/skills/use",
        headers=headers,
        params={"demo": True},
        json={"skill_id": skill_id},
    )
    assert use_res.status_code == 200, use_res.text
    assert use_res.json()["selected_skill"]["id"] == skill_id

    db.expire_all()
    skill_model = db.get(Skill, uuid.UUID(skill_id))
    assert skill_model is not None
    assert skill_model.usage_count == 0
