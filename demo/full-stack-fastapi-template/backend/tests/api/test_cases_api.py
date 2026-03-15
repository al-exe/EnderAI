import uuid

from sqlalchemy import text
from sqlmodel import Session


def _ensure_case_tables(db: Session) -> None:
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
              last_touched_at timestamptz not null default now()
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


def _ensure_legacy_case_tables(db: Session) -> None:
    db.connection().execute(text("drop table if exists public.execution cascade"))
    db.connection().execute(text("drop table if exists public.thread cascade"))
    db.connection().execute(
        text(
            """
            create table if not exists public.thread (
              id uuid primary key,
              title text not null,
              workflow_key text not null,
              created_at timestamptz not null default now(),
              last_touched_at timestamptz not null default now()
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
              ended_at timestamptz,
              status text not null default 'aborted',
              summary text
            );
            """
        )
    )
    db.commit()


def test_cases_round_trip_and_render_views(client, normal_user_token_headers, db: Session) -> None:
    _ensure_case_tables(db)

    payload = {
        "thread": {
            "title": "Core model hydration mismatch",
            "workflow_key": "core_model",
            "intent_key": "case_schema",
        },
        "execution": {
            "status": "running",
            "summary": "Investigate why case hydration omits command history",
        },
    }

    started = client.post("/api/v1/executions/start", headers=normal_user_token_headers, json=payload)
    assert started.status_code == 201, started.text
    started_body = started.json()
    case_id = started_body["execution"]["id"]
    topic_id = started_body["thread"]["id"]

    case_res = client.get(f"/api/v1/cases/{case_id}", headers=normal_user_token_headers)
    assert case_res.status_code == 200, case_res.text
    case_body = case_res.json()
    assert case_body["id"] == case_id
    assert case_body["topic_id"] == topic_id
    assert case_body["title"] == "Investigate why case hydration omits command history"
    assert case_body["summary_current"] == "Investigate why case hydration omits command history"
    assert case_body["context_pack_snapshot"]["topic_id"] == topic_id
    assert case_body["context_pack_snapshot"]["case_id"] == case_id

    updated = client.patch(
        f"/api/v1/cases/{case_id}",
        headers=normal_user_token_headers,
        json={
            "title": "Hydration mismatch investigation",
            "source": "chat",
            "input_summary": "Agent hydration dropped useful commands from the prior case.",
            "summary_current": "Case schema now stores commands, hypotheses, and changes in one document.",
            "files": ["backend/app/api/routes/cases.py", "backend/app/core/cases.py"],
            "symbols": ["build_case_public", "read_case_hydration"],
            "errors": ["missing command history"],
            "symptoms": ["hydration payload is too sparse"],
            "commands": [
                {
                    "cmd": "pytest backend/tests/api/test_cases_api.py",
                    "purpose": "validate the canonical case schema",
                    "salient_result": "passes",
                }
            ],
            "hypotheses": [
                {
                    "statement": "execution summary drifted from the structured case document",
                    "status": "supported",
                    "evidence": "summary now derives from the same stored record",
                },
                {
                    "statement": "topic matching still needs a dedicated rollup pipeline",
                    "status": "open",
                },
            ],
            "changes": [
                {
                    "kind": "code",
                    "summary": "added the cases compatibility API",
                    "files": ["backend/app/api/routes/cases.py"],
                    "refs": ["KAN-9", "KAN-10"],
                }
            ],
            "outcome": "Case schema and views stay aligned through one canonical record.",
            "next_steps": ["build topic matching", "derive topic rollups"],
            "context_pack_snapshot": {
                "topic_id": topic_id,
                "case_id": case_id,
                "topic_summary": "Core model workstream",
                "matched_signals": ["missing command history", "hydration payload is too sparse"],
                "canonical_files": ["backend/app/api/routes/cases.py"],
                "canonical_symbols": ["build_case_public"],
                "canonical_errors": ["missing command history"],
                "canonical_symptoms": ["hydration payload is too sparse"],
                "pinned_takeaways": ["one case record should drive both views"],
                "negative_history": ["do not split human and AI logs"],
                "builder_version": "v1",
            },
        },
    )
    assert updated.status_code == 200, updated.text
    updated_body = updated.json()
    assert updated_body["title"] == "Hydration mismatch investigation"
    assert updated_body["source"] == "chat"
    assert updated_body["commands"][0]["cmd"] == "pytest backend/tests/api/test_cases_api.py"
    assert updated_body["context_pack_snapshot"]["builder_version"] == "v1"

    execution_res = client.get(f"/api/v1/executions/{case_id}", headers=normal_user_token_headers)
    assert execution_res.status_code == 200, execution_res.text
    assert execution_res.json()["summary"] == updated_body["summary_current"]

    cases_res = client.get("/api/v1/cases/", headers=normal_user_token_headers)
    assert cases_res.status_code == 200, cases_res.text
    assert cases_res.json()["count"] >= 1

    memo_res = client.get(f"/api/v1/cases/{case_id}/memo", headers=normal_user_token_headers)
    assert memo_res.status_code == 200, memo_res.text
    memo_body = memo_res.json()
    assert memo_body["summary_current"] == updated_body["summary_current"]
    assert memo_body["commands"][0]["cmd"] == updated_body["commands"][0]["cmd"]
    assert memo_body["outcome"] == updated_body["outcome"]

    hydration_res = client.get(
        f"/api/v1/cases/{case_id}/hydration", headers=normal_user_token_headers
    )
    assert hydration_res.status_code == 200, hydration_res.text
    hydration_body = hydration_res.json()
    assert hydration_body["signals"]["files"] == updated_body["files"]
    assert hydration_body["matched_signals"][0] == "missing command history"
    assert hydration_body["supported_hypotheses"] == [
        "execution summary drifted from the structured case document"
    ]
    assert hydration_body["open_questions"] == [
        "topic matching still needs a dedicated rollup pipeline"
    ]


def test_cases_read_legacy_executions_without_case_columns(
    client, normal_user_token_headers, db: Session
) -> None:
    _ensure_legacy_case_tables(db)

    thread_id = uuid.uuid4()
    case_id = uuid.uuid4()
    db.connection().execute(
        text(
            "insert into public.thread (id, title, workflow_key) values (:id, :title, :workflow_key)"
        ),
        {"id": thread_id, "title": "Legacy thread", "workflow_key": "legacy"},
    )
    db.connection().execute(
        text(
            "insert into public.execution (id, thread_id, status, summary) values (:id, :thread_id, :status, :summary)"
        ),
        {
            "id": case_id,
            "thread_id": thread_id,
            "status": "running",
            "summary": "Legacy execution summary",
        },
    )
    db.commit()

    case_res = client.get(f"/api/v1/cases/{case_id}", headers=normal_user_token_headers)
    assert case_res.status_code == 200, case_res.text
    case_body = case_res.json()
    assert case_body["title"] == "Legacy execution summary"
    assert case_body["summary_current"] == "Legacy execution summary"
    assert case_body["context_pack_snapshot"]["topic_id"] == str(thread_id)

    patch_res = client.patch(
        f"/api/v1/cases/{case_id}",
        headers=normal_user_token_headers,
        json={"summary_current": "should fail on legacy schema"},
    )
    assert patch_res.status_code == 501, patch_res.text
