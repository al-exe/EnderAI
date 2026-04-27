import uuid

from sqlmodel import Session

from app.models import CaseRecord
from tests.utils.user import authentication_token_from_email


def _current_user_id(client, headers: dict[str, str]) -> str:
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_cases_round_trip_and_render_views(client, normal_user_token_headers, db: Session) -> None:
    topic_res = client.post(
        "/api/v1/topics/",
        headers=normal_user_token_headers,
        json={
            "title": "Core model hydration mismatch",
            "workflow_key": "core_model",
            "description": "Track hydration mismatches in the new canonical model.",
        },
    )
    assert topic_res.status_code == 201, topic_res.text
    topic_body = topic_res.json()
    topic_id = topic_body["id"]

    case_res = client.post(
        "/api/v1/cases/",
        headers=normal_user_token_headers,
        json={
            "topic_id": topic_id,
            "title": "Investigate why case hydration omits command history",
            "status": "running",
            "input_summary": "Case hydration is omitting recorded commands.",
            "summary_current": "Investigate why case hydration omits command history",
        },
    )
    assert case_res.status_code == 201, case_res.text
    case_body = case_res.json()
    case_id = case_body["id"]
    assert case_body["topic_id"] == topic_id
    assert case_body["topic_title"] == topic_body["title"]
    assert case_body["context_pack_snapshot"]["topic_id"] == topic_id
    assert case_body["context_pack_snapshot"]["case_id"] == case_id

    updated = client.patch(
        f"/api/v1/cases/{case_id}",
        headers=normal_user_token_headers,
        json={
            "title": "Hydration mismatch debugging",
            "status": "done",
            "source": "ai-agent",
            "input_summary": "Case hydration omitted commands and file clues.",
            "summary_current": "Canonical case document is now aligned.",
            "files": ["backend/app/api/routes/cases.py", "backend/app/core/cases.py"],
            "symbols": ["build_case_public", "render_case_hydration"],
            "errors": ["hydration omitted commands"],
            "symptoms": ["incomplete case context"],
            "commands": [
                {
                    "cmd": "pytest backend/tests/api/test_cases_api.py",
                    "purpose": "verify canonical cases API",
                    "salient_result": "passed",
                }
            ],
            "hypotheses": [
                {
                    "statement": "case summary drifted from the structured case document",
                    "status": "supported",
                    "evidence": "summary_current and case_data were aligned",
                }
            ],
            "changes": [
                {
                    "kind": "code",
                    "summary": "added the canonical cases API",
                    "files": ["backend/app/api/routes/cases.py"],
                    "refs": ["KAN-29"],
                }
            ],
            "outcome": "Case hydration is now consistent.",
            "next_steps": ["Verify the frontend reads canonical cases."],
            "context_pack_snapshot": {
                "topic_id": topic_id,
                "case_id": case_id,
                "confidence": "high",
                "topic_summary": "Hydration mismatch investigation",
                "matched_signals": ["hydration omitted commands"],
                "canonical_files": ["backend/app/api/routes/cases.py"],
            },
        },
    )
    assert updated.status_code == 200, updated.text
    updated_body = updated.json()
    assert updated_body["title"] == "Hydration mismatch debugging"
    assert updated_body["status"] == "done"
    assert updated_body["files"] == [
        "backend/app/api/routes/cases.py",
        "backend/app/core/cases.py",
    ]
    assert updated_body["commands"][0]["cmd"] == "pytest backend/tests/api/test_cases_api.py"

    partial_snapshot = client.patch(
        f"/api/v1/cases/{case_id}",
        headers=normal_user_token_headers,
        json={
            "context_pack_snapshot": {
                "builder_version": "v2",
                "topic_id": str(uuid.uuid4()),
                "case_id": str(uuid.uuid4()),
            }
        },
    )
    assert partial_snapshot.status_code == 200, partial_snapshot.text
    partial_snapshot_body = partial_snapshot.json()
    assert partial_snapshot_body["context_pack_snapshot"]["builder_version"] == "v2"
    assert partial_snapshot_body["context_pack_snapshot"]["topic_id"] == topic_id
    assert partial_snapshot_body["context_pack_snapshot"]["case_id"] == case_id
    assert partial_snapshot_body["context_pack_snapshot"]["canonical_files"] == [
        "backend/app/api/routes/cases.py"
    ]

    db.expire_all()
    case_record = db.get(CaseRecord, uuid.UUID(case_id))
    assert case_record is not None
    assert "summary_current" not in case_record.case_data

    cases_res = client.get("/api/v1/cases/", headers=normal_user_token_headers)
    assert cases_res.status_code == 200, cases_res.text
    assert cases_res.json()["count"] >= 1

    memo_res = client.get(f"/api/v1/cases/{case_id}/memo", headers=normal_user_token_headers)
    assert memo_res.status_code == 200, memo_res.text
    assert memo_res.json()["title"] == "Hydration mismatch debugging"

    hydration_res = client.get(
        f"/api/v1/cases/{case_id}/hydration", headers=normal_user_token_headers
    )
    assert hydration_res.status_code == 200, hydration_res.text
    hydration_body = hydration_res.json()
    assert hydration_body["supported_hypotheses"] == [
        "case summary drifted from the structured case document"
    ]
    assert hydration_body["context_pack_snapshot"]["canonical_files"] == [
        "backend/app/api/routes/cases.py"
    ]

    event_res = client.post(
        f"/api/v1/cases/{case_id}/events",
        headers=normal_user_token_headers,
        json={
            "type": "mcp",
            "message": "Logged a canonical case event",
            "data": {"ok": True, "ticket": "KAN-29"},
        },
    )
    assert event_res.status_code == 201, event_res.text
    event_id = event_res.json()["id"]
    assert event_res.json()["case_id"] == case_id

    events_res = client.get(
        f"/api/v1/cases/{case_id}/events", headers=normal_user_token_headers
    )
    assert events_res.status_code == 200, events_res.text
    events_body = events_res.json()
    assert events_body["count"] >= 1
    assert any(event["id"] == event_id for event in events_body["data"])


def test_cases_are_scoped_to_the_current_user(client, normal_user_token_headers, db: Session) -> None:
    owner_id = _current_user_id(client, normal_user_token_headers)
    other_headers = authentication_token_from_email(
        client=client,
        email=f"other-{uuid.uuid4()}@example.com",
        db=db,
    )

    topic_res = client.post(
        "/api/v1/topics/",
        headers=normal_user_token_headers,
        json={
            "title": "Private case ownership",
            "workflow_key": f"private_case_ownership_{uuid.uuid4().hex[:8]}",
            "owner_ids": [str(uuid.uuid4())],
        },
    )
    assert topic_res.status_code == 201, topic_res.text
    topic_id = topic_res.json()["id"]
    assert topic_res.json()["owner_ids"] == [owner_id]

    mismatched_actor_res = client.post(
        "/api/v1/cases/",
        headers=normal_user_token_headers,
        json={
            "topic_id": topic_id,
            "title": "Should reject actor impersonation",
            "actor_id": str(uuid.uuid4()),
        },
    )
    assert mismatched_actor_res.status_code == 403, mismatched_actor_res.text

    case_res = client.post(
        "/api/v1/cases/",
        headers=normal_user_token_headers,
        json={
            "topic_id": topic_id,
            "title": "Owner-only case",
            "summary_current": "Only the owning user should be able to view this case.",
            "files": ["backend/app/api/routes/cases.py"],
        },
    )
    assert case_res.status_code == 201, case_res.text
    case_body = case_res.json()
    case_id = case_body["id"]
    assert case_body["actor_id"] == owner_id

    other_cases_res = client.get("/api/v1/cases/", headers=other_headers)
    assert other_cases_res.status_code == 200, other_cases_res.text
    assert all(row["id"] != case_id for row in other_cases_res.json()["data"])

    for method, path, payload in [
        ("get", f"/api/v1/cases/{case_id}", None),
        ("get", f"/api/v1/cases/{case_id}/memo", None),
        ("get", f"/api/v1/cases/{case_id}/hydration", None),
        ("get", f"/api/v1/cases/{case_id}/events", None),
        ("patch", f"/api/v1/cases/{case_id}", {"summary_current": "intrusion"}),
        (
            "post",
            f"/api/v1/cases/{case_id}/events",
            {"type": "mcp", "message": "should not be allowed"},
        ),
        (
            "post",
            "/api/v1/cases/",
            {"topic_id": topic_id, "title": "Should not create under another user's topic"},
        ),
    ]:
        request_kwargs = {"headers": other_headers}
        if payload is not None:
            request_kwargs["json"] = payload
        response = getattr(client, method)(path, **request_kwargs)
        assert response.status_code == 404, response.text

    owner_actor_patch = client.patch(
        f"/api/v1/cases/{case_id}",
        headers=normal_user_token_headers,
        json={"actor_id": str(uuid.uuid4())},
    )
    assert owner_actor_patch.status_code == 403, owner_actor_patch.text
