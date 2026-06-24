def test_global_search_returns_grouped_topic_case_and_skill_hits(
    client,
    normal_user_token_headers,
) -> None:
    topic_res = client.post(
        "/api/v1/topics/",
        headers=normal_user_token_headers,
        json={
            "title": "Global search rollout",
            "workflow_key": "global_search",
            "description": "Track the new top-bar search experience across Topics and Cases.",
            "aliases": ["header search", "search bar"],
        },
    )
    assert topic_res.status_code == 201, topic_res.text
    topic_id = topic_res.json()["id"]

    case_res = client.post(
        "/api/v1/cases/",
        headers=normal_user_token_headers,
        json={
            "topic_id": topic_id,
            "title": "Add grouped search endpoint",
            "status": "done",
            "summary_current": "Mixed search endpoint returns grouped Topic and Case results.",
            "files": ["backend/app/api/routes/search.py"],
            "symbols": ["search_topics_and_cases"],
            "errors": ["missing grouped results"],
            "hypotheses": [
                {
                    "statement": "search should scan route metadata and case notes",
                    "status": "supported",
                    "evidence": "querying by file and hypothesis now returns the case",
                }
            ],
            "changes": [
                {
                    "kind": "code",
                    "summary": "implemented grouped search endpoint",
                    "files": ["backend/app/api/routes/search.py"],
                    "refs": ["KAN-112"],
                }
            ],
            "outcome": "Header search can now resolve Topics and Cases.",
            "context_pack_snapshot": {
                "topic_summary": "Global search implementation",
                "matched_signals": ["backend/app/api/routes/search.py"],
                "canonical_files": ["backend/app/api/routes/search.py"],
                "questions": ["should the header search use a grouped dropdown?"],
            },
        },
    )
    assert case_res.status_code == 201, case_res.text
    case_id = case_res.json()["id"]

    skill_res = client.post(
        "/api/v1/skills/generate",
        headers=normal_user_token_headers,
        json={"topic_id": topic_id},
    )
    assert skill_res.status_code == 201, skill_res.text
    skill_id = skill_res.json()["id"]

    title_match = client.get(
        "/api/v1/search/",
        headers=normal_user_token_headers,
        params={"q": "Global search rollout"},
    )
    assert title_match.status_code == 200, title_match.text
    title_body = title_match.json()
    assert title_body["topic_count"] >= 1
    assert title_body["topics"][0]["id"] == topic_id
    assert title_body["topics"][0]["route"] == "/topics"
    assert title_body["topics"][0]["route_search"]["topicId"] == topic_id

    file_match = client.get(
        "/api/v1/search/",
        headers=normal_user_token_headers,
        params={"q": "backend/app/api/routes/search.py"},
    )
    assert file_match.status_code == 200, file_match.text
    file_body = file_match.json()
    assert file_body["case_count"] >= 1
    assert file_body["cases"][0]["id"] == case_id
    assert file_body["cases"][0]["route"] == "/cases"
    assert file_body["cases"][0]["route_search"]["caseId"] == case_id
    assert file_body["cases"][0]["subtitle"] == "Global search rollout"

    hypothesis_match = client.get(
        "/api/v1/search/",
        headers=normal_user_token_headers,
        params={"q": "grouped dropdown"},
    )
    assert hypothesis_match.status_code == 200, hypothesis_match.text
    hypothesis_body = hypothesis_match.json()
    assert hypothesis_body["cases"][0]["id"] == case_id

    skill_match = client.get(
        "/api/v1/search/",
        headers=normal_user_token_headers,
        params={"q": "Workflow Skill"},
    )
    assert skill_match.status_code == 200, skill_match.text
    skill_body = skill_match.json()
    assert skill_body["skill_count"] >= 1
    assert skill_body["skills"][0]["id"] == skill_id
    assert skill_body["skills"][0]["route"] == "/skills"
    assert skill_body["skills"][0]["route_search"]["skillId"] == skill_id


def test_global_search_rejects_short_queries(client, normal_user_token_headers) -> None:
    response = client.get(
        "/api/v1/search/",
        headers=normal_user_token_headers,
        params={"q": " "},
    )
    assert response.status_code == 422, response.text


def test_global_search_returns_taskforce_profiles_documents_and_sessions(
    client,
    normal_user_token_headers,
) -> None:
    profile_res = client.post(
        "/api/v1/v2/agents",
        headers=normal_user_token_headers,
        json={
            "name": "Quartz Reliability",
            "role": "Distributed systems specialist",
            "short_description": "Diagnoses quartz queue failures.",
            "domain_tags": ["quartz", "queues"],
        },
    )
    assert profile_res.status_code == 201, profile_res.text

    document_res = client.post(
        "/api/v1/v2/documents/",
        headers=normal_user_token_headers,
        json={
            "title": "Quartz queue recovery",
            "description": "Runbook for restoring quartz workers.",
            "human_summary": "Quartz workers recover after lease rotation.",
        },
    )
    assert document_res.status_code == 201, document_res.text

    session_res = client.post(
        "/api/v1/v2/taskforce/session/start",
        headers=normal_user_token_headers,
        json={
            "prompt": "Investigate the quartz queue stall",
            "cwd": "/workspace/quartz-service",
            "client": "codex",
        },
    )
    assert session_res.status_code == 201, session_res.text

    search_res = client.get(
        "/api/v1/search/",
        headers=normal_user_token_headers,
        params={"q": "quartz"},
    )
    assert search_res.status_code == 200, search_res.text
    body = search_res.json()

    assert body["profiles"][0]["title"] == "Quartz Reliability"
    assert body["profiles"][0]["href"].startswith("/v2/agents/")
    assert body["documents"][0]["title"] == "Quartz queue recovery"
    assert body["documents"][0]["href"].startswith("/v2/library/")
    assert body["sessions"][0]["href"].startswith("/v2/sessions/")
