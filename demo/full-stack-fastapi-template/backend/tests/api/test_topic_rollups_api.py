import uuid

from sqlmodel import Session

from app.models import CaseRecord, Topic, get_datetime_utc
from tests.utils.user import authentication_token_from_email


def _current_user_id(client, headers: dict[str, str]) -> str:
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_topic_rollups_match_and_context_pack(client, normal_user_token_headers, db: Session) -> None:
    topic_a = client.post(
        "/api/v1/topics/",
        headers=normal_user_token_headers,
        json={
            "title": "Case hydration regressions",
            "workflow_key": "case_hydration",
            "description": "Track hydration gaps in the canonical case model.",
            "aliases": ["hydration"],
        },
    )
    assert topic_a.status_code == 201, topic_a.text
    topic_a_id = topic_a.json()["id"]

    case_a = client.post(
        "/api/v1/cases/",
        headers=normal_user_token_headers,
        json={
            "topic_id": topic_a_id,
            "title": "Investigate sparse case hydration",
            "status": "done",
            "summary_current": "Hydration omits commands and file clues.",
            "files": ["backend/app/api/routes/cases.py"],
            "symbols": ["render_case_hydration"],
            "errors": ["hydration omitted commands"],
            "symptoms": ["sparse context"],
            "hypotheses": [
                {"statement": "case payload is missing command history", "status": "supported"}
            ],
            "outcome": "Hydration snapshot restored command history.",
        },
    )
    assert case_a.status_code == 201, case_a.text
    case_a_id = case_a.json()["id"]

    topic_b = client.post(
        "/api/v1/topics/",
        headers=normal_user_token_headers,
        json={
            "title": "Agent credential validation",
            "workflow_key": "agent_tokens",
            "description": "Track backend and MCP token validation issues.",
            "aliases": ["tokens", "mcp"],
        },
    )
    assert topic_b.status_code == 201, topic_b.text
    topic_b_id = topic_b.json()["id"]

    case_b = client.post(
        "/api/v1/cases/",
        headers=normal_user_token_headers,
        json={
            "topic_id": topic_b_id,
            "title": "Investigate rejected MCP agent tokens",
            "status": "done",
            "summary_current": "Hosted MCP token validation should reject inactive users.",
            "files": ["backend/app/api/deps.py"],
            "symbols": ["validate_agent_credential_token"],
            "errors": ["Inactive user"],
            "symptoms": ["MCP token rejected"],
            "outcome": "Validation now checks inactive users before updating last_used_at.",
        },
    )
    assert case_b.status_code == 201, case_b.text
    case_b_id = case_b.json()["id"]

    topic_a_get = client.get(f"/api/v1/topics/{topic_a_id}", headers=normal_user_token_headers)
    assert topic_a_get.status_code == 200, topic_a_get.text
    assert topic_a_get.json()["workflow_key"] == "case-hydration"
    assert "case-hydration" not in topic_a_get.json()["aliases"]

    rollup_a = client.get(f"/api/v1/topics/{topic_a_id}/rollup", headers=normal_user_token_headers)
    assert rollup_a.status_code == 200, rollup_a.text
    rollup_a_body = rollup_a.json()
    assert rollup_a_body["canonical_files"] == ["backend/app/api/routes/cases.py"]
    assert rollup_a_body["representative_case_ids"] == [case_a_id]

    db.expire_all()
    topic_model = db.get(Topic, uuid.UUID(topic_a_id))
    assert topic_model is not None
    topic_model.rollup_summary = None
    topic_model.rollup_data = {}
    db.add(topic_model)
    db.commit()

    refresh_b = client.post(
        f"/api/v1/topics/{topic_b_id}/rollup/refresh",
        headers=normal_user_token_headers,
    )
    assert refresh_b.status_code == 200, refresh_b.text
    assert refresh_b.json()["canonical_errors"] == ["Inactive user"]

    match_res = client.post(
        "/api/v1/topics/match",
        headers=normal_user_token_headers,
        json={
            "title": "Hydration mismatch",
            "request_summary": "Case hydration is omitting commands.",
            "files": ["backend/app/api/routes/cases.py"],
            "symbols": ["render_case_hydration"],
            "errors": ["hydration omitted commands"],
            "symptoms": ["sparse context"],
        },
    )
    assert match_res.status_code == 200, match_res.text
    match_body = match_res.json()
    assert match_body["candidates"][0]["topic"]["id"] == topic_a_id
    assert match_body["policy"]["max_topics"] >= 1
    assert match_body["candidates"][0]["topic"]["canonical_files"] == [
        "backend/app/api/routes/cases.py"
    ]

    pack_res = client.post(
        "/api/v1/context-packs/build",
        headers=normal_user_token_headers,
        json={
            "title": "Hydration mismatch",
            "request_summary": "Case hydration is omitting commands.",
            "files": ["backend/app/api/routes/cases.py"],
            "symbols": ["render_case_hydration"],
            "errors": ["hydration omitted commands"],
            "symptoms": ["sparse context"],
            "max_topics": 1,
            "max_cases_per_topic": 2,
        },
    )
    assert pack_res.status_code == 200, pack_res.text
    pack_body = pack_res.json()
    assert pack_body["selected_topic_ids"] == [topic_a_id]
    assert pack_body["selected_case_ids"] == [case_a_id]
    assert pack_body["relevant_cases"][0]["case_id"] == case_a_id
    assert pack_body["context_pack_snapshot"]["canonical_files"] == ["backend/app/api/routes/cases.py"]
    assert case_b_id not in pack_body["selected_case_ids"]


def test_topic_match_groups_related_frontend_table_work(client, normal_user_token_headers) -> None:
    topic = client.post(
        "/api/v1/topics/",
        headers=normal_user_token_headers,
        json={
            "title": "Frontend table layout",
            "workflow_key": "frontend_table_layout",
            "description": "Track shared Topics/Cases table layout and scrolling fixes.",
            "aliases": ["topics cases table", "split table"],
        },
    )
    assert topic.status_code == 201, topic.text
    topic_id = topic.json()["id"]

    case = client.post(
        "/api/v1/cases/",
        headers=normal_user_token_headers,
        json={
            "topic_id": topic_id,
            "title": "Fix topics/cases table header alignment",
            "status": "done",
            "summary_current": "Shared frontend table layout now keeps headers aligned with body rows.",
            "files": ["src/components/Common/SplitDataTable.tsx"],
            "symbols": ["SplitDataTable"],
            "symptoms": ["header columns drift while scrolling"],
            "outcome": "Topics/Cases table header alignment is consistent while scrolling.",
        },
    )
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]

    match = client.post(
        "/api/v1/topics/match",
        headers=normal_user_token_headers,
        json={
            "title": "Fix split table overflow clipping",
            "request_summary": "Keep frontend table scrolling and alignment fixes grouped together.",
            "files": ["src/components/Common/SplitScrollableTable.tsx"],
            "contexts": [
                "frontend table layout",
                "topics cases table header alignment",
            ],
        },
    )
    assert match.status_code == 200, match.text
    match_body = match.json()
    assert match_body["policy"]["confidence"] in {"high", "medium"}
    assert match_body["candidates"][0]["topic"]["id"] == topic_id

    pack = client.post(
        "/api/v1/context-packs/build",
        headers=normal_user_token_headers,
        json={
            "title": "Fix split table overflow clipping",
            "request_summary": "Keep frontend table scrolling and alignment fixes grouped together.",
            "files": ["src/components/Common/SplitScrollableTable.tsx"],
            "contexts": [
                "frontend table layout",
                "topics cases table header alignment",
            ],
            "max_topics": 1,
            "max_cases_per_topic": 2,
        },
    )
    assert pack.status_code == 200, pack.text
    pack_body = pack.json()
    assert pack_body["selected_topic_ids"] == [topic_id]
    assert pack_body["selected_case_ids"] == [case_id]


def test_topic_access_and_matching_are_scoped_to_the_current_user(
    client,
    normal_user_token_headers,
    db: Session,
) -> None:
    owner_id = _current_user_id(client, normal_user_token_headers)
    other_headers = authentication_token_from_email(
        client=client,
        email=f"topic-other-{uuid.uuid4()}@example.com",
        db=db,
    )

    topic = client.post(
        "/api/v1/topics/",
        headers=normal_user_token_headers,
        json={
            "title": "Private frontend bug stream",
            "workflow_key": f"private_frontend_bug_stream_{uuid.uuid4().hex[:8]}",
            "owner_ids": [str(uuid.uuid4())],
        },
    )
    assert topic.status_code == 201, topic.text
    topic_body = topic.json()
    topic_id = topic_body["id"]
    assert topic_body["owner_ids"] == [owner_id]

    case = client.post(
        "/api/v1/cases/",
        headers=normal_user_token_headers,
        json={
            "topic_id": topic_id,
            "title": "Private table overflow regression",
            "status": "done",
            "summary_current": "Only the owner should be able to match or hydrate against this case.",
            "files": ["src/components/Common/SplitDataTable.tsx"],
            "symbols": ["SplitDataTable"],
            "symptoms": ["table overflow"],
        },
    )
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]

    list_res = client.get("/api/v1/topics/", headers=other_headers)
    assert list_res.status_code == 200, list_res.text
    assert all(row["id"] != topic_id for row in list_res.json()["data"])

    for method, path, payload in [
        ("get", f"/api/v1/topics/{topic_id}", None),
        ("get", f"/api/v1/topics/{topic_id}/rollup", None),
        ("post", f"/api/v1/topics/{topic_id}/rollup/refresh", None),
    ]:
        request_kwargs = {"headers": other_headers}
        if payload is not None:
            request_kwargs["json"] = payload
        response = getattr(client, method)(path, **request_kwargs)
        assert response.status_code == 404, response.text

    match_res = client.post(
        "/api/v1/topics/match",
        headers=other_headers,
        json={
            "title": "Private table overflow regression",
            "request_summary": "This should not match another user's topic.",
            "files": ["src/components/Common/SplitDataTable.tsx"],
            "symbols": ["SplitDataTable"],
            "symptoms": ["table overflow"],
        },
    )
    assert match_res.status_code == 200, match_res.text
    assert match_res.json()["candidates"] == []

    pack_res = client.post(
        "/api/v1/context-packs/build",
        headers=other_headers,
        json={
            "title": "Private table overflow regression",
            "request_summary": "This should not hydrate from another user's topic.",
            "files": ["src/components/Common/SplitDataTable.tsx"],
            "symbols": ["SplitDataTable"],
            "symptoms": ["table overflow"],
            "max_topics": 1,
            "max_cases_per_topic": 2,
        },
    )
    assert pack_res.status_code == 200, pack_res.text
    pack_body = pack_res.json()
    assert pack_body["selected_topic_ids"] == []
    assert pack_body["selected_case_ids"] == []
    assert pack_body["relevant_cases"] == []
    assert case_id not in pack_body["selected_case_ids"]

    explicit_pack_res = client.post(
        "/api/v1/context-packs/build",
        headers=other_headers,
        json={"topic_id": topic_id},
    )
    assert explicit_pack_res.status_code == 404, explicit_pack_res.text

    owner_update = client.patch(
        f"/api/v1/topics/{topic_id}",
        headers=normal_user_token_headers,
        json={"owner_ids": [str(uuid.uuid4())]},
    )
    assert owner_update.status_code == 403, owner_update.text


def test_legacy_orphan_topics_and_cases_are_claimed_for_current_user(
    client,
    normal_user_token_headers,
    db: Session,
) -> None:
    owner_id = uuid.UUID(_current_user_id(client, normal_user_token_headers))
    other_headers = authentication_token_from_email(
        client=client,
        email=f"legacy-other-{uuid.uuid4()}@example.com",
        db=db,
    )

    now = get_datetime_utc()
    topic_id = uuid.uuid4()
    case_id = uuid.uuid4()
    topic = Topic(
        id=topic_id,
        title="Legacy unowned topic",
        slug=f"legacy-unowned-topic-{uuid.uuid4().hex[:8]}",
        workflow_key=f"legacy_unowned_topic_{uuid.uuid4().hex[:8]}",
        status="open",
        owner_ids=[],
        created_at=now,
        updated_at=now,
        last_used_at=now,
    )
    case_record = CaseRecord(
        id=case_id,
        topic_id=topic_id,
        title="Legacy unowned case",
        opened_at=now,
        updated_at=now,
        status="done",
        actor_id=None,
        summary_current="A legacy case without actor ownership.",
        case_data={"files": ["backend/app/core/topics.py"]},
    )
    db.add(topic)
    db.commit()
    db.add(case_record)
    db.commit()

    topics_res = client.get("/api/v1/topics/", headers=normal_user_token_headers)
    assert topics_res.status_code == 200, topics_res.text
    assert any(row["id"] == str(topic_id) for row in topics_res.json()["data"])

    cases_res = client.get("/api/v1/cases/", headers=normal_user_token_headers)
    assert cases_res.status_code == 200, cases_res.text
    assert any(row["id"] == str(case_id) for row in cases_res.json()["data"])

    db.expire_all()
    claimed_topic = db.get(Topic, topic_id)
    claimed_case = db.get(CaseRecord, case_id)
    assert claimed_topic is not None
    assert claimed_case is not None
    assert claimed_topic.owner_ids == [str(owner_id)]
    assert claimed_case.actor_id == owner_id

    other_topics_res = client.get("/api/v1/topics/", headers=other_headers)
    assert other_topics_res.status_code == 200, other_topics_res.text
    assert all(row["id"] != str(topic_id) for row in other_topics_res.json()["data"])

    other_cases_res = client.get("/api/v1/cases/", headers=other_headers)
    assert other_cases_res.status_code == 200, other_cases_res.text
    assert all(row["id"] != str(case_id) for row in other_cases_res.json()["data"])
