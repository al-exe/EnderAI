from sqlalchemy import text
from sqlmodel import Session


def _ensure_topic_case_tables(db: Session) -> None:
    db.connection().execute(
        text(
            """
            create table if not exists public.thread (
              id uuid primary key,
              title text not null,
              workflow_key text not null,
              intent_key text,
              goal text,
              acceptance_criteria text,
              systems_touched jsonb not null default '{}'::jsonb,
              risk_level text not null default 'read_only',
              status text not null default 'open',
              created_at timestamptz not null default now(),
              last_touched_at timestamptz not null default now(),
              topic_data jsonb not null default '{}'::jsonb,
              topic_rollup jsonb not null default '{}'::jsonb
            );
            """
        )
    )
    db.connection().execute(
        text(
            """
            create table if not exists public.execution (
              id uuid primary key,
              thread_id uuid not null references public.thread(id) on delete cascade,
              targets jsonb not null default '[]'::jsonb,
              started_at timestamptz not null default now(),
              updated_at timestamptz not null default now(),
              ended_at timestamptz,
              status text not null default 'aborted',
              summary text,
              case_data jsonb not null default '{}'::jsonb,
              context_pack_snapshot jsonb not null default '{}'::jsonb
            );
            """
        )
    )
    db.commit()


def test_topic_rollup_match_and_context_pack(
    client, superuser_token_headers, normal_user_token_headers, db: Session
) -> None:
    _ensure_topic_case_tables(db)

    started_a = client.post(
        "/api/v1/executions/start",
        headers=normal_user_token_headers,
        json={
            "thread": {
                "title": "Core model hydration",
                "workflow_key": "core_model",
                "intent_key": "hydration_gap",
            },
            "execution": {"summary": "Investigate sparse case hydration"},
        },
    )
    assert started_a.status_code == 201, started_a.text
    topic_a_id = started_a.json()["thread"]["id"]
    case_a_id = started_a.json()["execution"]["id"]

    updated_a = client.patch(
        f"/api/v1/cases/{case_a_id}",
        headers=normal_user_token_headers,
        json={
            "files": ["backend/app/api/routes/cases.py"],
            "symbols": ["build_case_public"],
            "errors": ["missing command history"],
            "symptoms": ["hydration payload too sparse"],
            "hypotheses": [
                {"statement": "rollups should derive from structured case signals", "status": "supported"},
                {"statement": "matching still needs broader topic vocabulary", "status": "open"},
            ],
            "changes": [
                {
                    "kind": "code",
                    "summary": "added canonical case routes",
                    "files": ["backend/app/api/routes/cases.py"],
                    "refs": ["KAN-9"],
                }
            ],
            "outcome": "One canonical case record now drives both memo and hydration views.",
            "next_steps": ["derive topic rollups", "build context packs"],
        },
    )
    assert updated_a.status_code == 200, updated_a.text

    started_b = client.post(
        "/api/v1/executions/start",
        headers=normal_user_token_headers,
        json={
            "thread": {
                "title": "Hosted MCP auth",
                "workflow_key": "hosted_mcp",
                "intent_key": "agent_tokens",
            },
            "execution": {"summary": "Investigate rejected MCP agent tokens"},
        },
    )
    assert started_b.status_code == 201, started_b.text
    topic_b_id = started_b.json()["thread"]["id"]
    case_b_id = started_b.json()["execution"]["id"]

    updated_b = client.patch(
        f"/api/v1/cases/{case_b_id}",
        headers=normal_user_token_headers,
        json={
            "files": ["mcp/enderai-api-mcp/src/mcpAuth.ts"],
            "symbols": ["validateBackendToken"],
            "errors": ["agent token rejected"],
            "symptoms": ["hosted MCP handshake fails"],
            "outcome": "MCP auth issues now stay scoped to the hosted MCP topic.",
        },
    )
    assert updated_b.status_code == 200, updated_b.text

    topic_a = client.get(f"/api/v1/topics/{topic_a_id}", headers=normal_user_token_headers)
    assert topic_a.status_code == 200, topic_a.text
    topic_a_body = topic_a.json()
    assert topic_a_body["case_count"] == 1
    assert topic_a_body["canonical_errors"] == ["missing command history"]
    assert topic_a_body["open_questions"] == ["matching still needs broader topic vocabulary"]
    assert topic_a_body["representative_case_ids"] == [case_a_id]

    rollup_a = client.get(f"/api/v1/topics/{topic_a_id}/rollup", headers=normal_user_token_headers)
    assert rollup_a.status_code == 200, rollup_a.text
    rollup_a_body = rollup_a.json()
    assert rollup_a_body["canonical_files"] == ["backend/app/api/routes/cases.py"]
    assert rollup_a_body["open_questions"] == ["matching still needs broader topic vocabulary"]

    db.connection().execute(
        text("update public.thread set topic_rollup = '{}'::jsonb where id = :topic_id"),
        {"topic_id": topic_a_id},
    )
    db.commit()

    refresh_b = client.post(
        f"/api/v1/topics/{topic_b_id}/rollup/refresh",
        headers=normal_user_token_headers,
    )
    assert refresh_b.status_code == 200, refresh_b.text
    assert refresh_b.json()["case_count"] == 1

    match = client.post(
        "/api/v1/topics/match",
        headers=normal_user_token_headers,
        json={
            "title": "Hydration gap",
            "request_summary": "Need prior command history for the core model case.",
            "files": ["backend/app/api/routes/cases.py"],
            "errors": ["missing command history"],
            "symptoms": ["hydration payload too sparse"],
        },
    )
    assert match.status_code == 200, match.text
    match_body = match.json()
    assert match_body["policy"]["confidence"] == "high"
    assert match_body["policy"]["max_topics"] == 1
    assert match_body["candidates"][0]["topic"]["id"] == topic_a_id

    context_pack = client.post(
        "/api/v1/context-packs/build",
        headers=normal_user_token_headers,
        json={
            "title": "Hydration gap",
            "request_summary": "Need prior command history for the core model case.",
            "files": ["backend/app/api/routes/cases.py"],
            "errors": ["missing command history"],
            "symptoms": ["hydration payload too sparse"],
            "max_cases_per_topic": 2,
        },
    )
    assert context_pack.status_code == 200, context_pack.text
    pack_body = context_pack.json()
    assert pack_body["selected_topic_ids"] == [topic_a_id]
    assert case_a_id in pack_body["selected_case_ids"]
    assert pack_body["relevant_cases"][0]["case_id"] == case_a_id
    assert pack_body["relevant_cases"][0]["why_selected"]
    assert pack_body["context_pack_snapshot"]["topic_id"] == topic_a_id
    assert pack_body["context_pack_snapshot"]["confidence"] == "high"
    assert pack_body["context_pack_snapshot"]["canonical_files"] == ["backend/app/api/routes/cases.py"]
    assert pack_body["context_pack_snapshot"]["questions"] == ["matching still needs broader topic vocabulary"]
    assert pack_body["context_pack_snapshot"]["relevant_cases"][0]["case_id"] == case_a_id
    assert "missing command history" in pack_body["context_pack_snapshot"]["matched_signals"]

    event_res = client.post(
        f"/api/v1/executions/{case_a_id}/events",
        headers=normal_user_token_headers,
        json={"type": "note", "message": "very noisy event-only activity"},
    )
    assert event_res.status_code == 201, event_res.text

    topic_after_event = client.get(
        f"/api/v1/topics/{topic_a_id}",
        headers=normal_user_token_headers,
    )
    assert topic_after_event.status_code == 200, topic_after_event.text
    assert topic_after_event.json()["rollup_summary"] == topic_a_body["rollup_summary"]

    deleted = client.delete(
        f"/api/v1/executions/{case_b_id}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200, deleted.text

    topic_b_after_delete = client.get(
        f"/api/v1/topics/{topic_b_id}",
        headers=normal_user_token_headers,
    )
    assert topic_b_after_delete.status_code == 200, topic_b_after_delete.text
    topic_b_after_delete_body = topic_b_after_delete.json()
    assert topic_b_after_delete_body["case_count"] == 0
    assert topic_b_after_delete_body["representative_case_ids"] == []
    assert topic_b_after_delete_body["recent_case_ids"] == []
