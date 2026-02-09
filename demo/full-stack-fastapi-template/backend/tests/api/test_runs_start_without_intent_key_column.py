from sqlalchemy import text
from sqlmodel import Session


def _ensure_memory_tables_without_intent_key(db: Session) -> None:
    # Ensure a "legacy" schema: public.task exists but has no intent_key column.
    db.connection().execute(text("drop table if exists public.run_library_link cascade"))
    db.connection().execute(text("drop table if exists public.run_event cascade"))
    db.connection().execute(text("drop table if exists public.run cascade"))
    db.connection().execute(text("drop table if exists public.task cascade"))

    db.connection().execute(
        text(
            """
            create table if not exists public.task (
              id uuid primary key,
              title text not null,
              workflow_key text not null,
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
            create table if not exists public.run (
              id uuid primary key,
              task_id uuid not null references public.task(id) on delete cascade,
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


def test_runs_start_works_without_intent_key_column(
    client, normal_user_token_headers, db: Session
) -> None:
    _ensure_memory_tables_without_intent_key(db)

    payload = {
        "task": {
            "title": "Delete item 11111111-1111-1111-1111-111111111111",
            "workflow_key": "customer_data_cleanup",
            "intent_key": "delete_item",
            "risk_level": "high",
            "status": "done",
            "systems_touched": {"endpoint": "/api/v1/items/{id}"},
        },
        "run": {"targets": [{"entity": "item", "id": "11111111-1111-1111-1111-111111111111"}]},
        "reuse_within_seconds": 60 * 60 * 24 * 365,
    }

    res1 = client.post("/api/v1/runs/start", headers=normal_user_token_headers, json=payload)
    assert res1.status_code == 201, res1.text
    body1 = res1.json()
    assert body1["reused_task"] is False
    task_id = body1["task"]["id"]

    payload2 = dict(payload)
    payload2["task"] = dict(payload["task"])
    payload2["task"]["title"] = "Delete item 22222222-2222-2222-2222-222222222222"

    res2 = client.post("/api/v1/runs/start", headers=normal_user_token_headers, json=payload2)
    assert res2.status_code == 201, res2.text
    body2 = res2.json()
    assert body2["reused_task"] is True
    assert body2["task"]["id"] == task_id

