import uuid

from sqlalchemy import text
from sqlmodel import Session


def _ensure_memory_tables(db: Session) -> None:
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
    db.connection().execute(text("alter table public.thread add column if not exists intent_key text"))
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
    db.connection().execute(
        text(
            """
            create table if not exists public.event (
              id bigserial primary key,
              execution_id uuid not null references public.execution(id) on delete cascade,
              ts timestamptz not null default now(),
              type text not null,
              message text,
              data jsonb not null default '{}'::jsonb,
              supersedes_event_id bigint references public.event(id)
            );
            """
        )
    )
    db.connection().execute(
        text(
            """
            create table if not exists public.artifact (
              id uuid primary key,
              workflow_key text not null,
              kind text not null,
              title text not null,
              body_mdc text not null,
              tags jsonb not null default '{}'::jsonb,
              source_refs jsonb not null default '[]'::jsonb,
              created_at timestamptz not null default now(),
              last_used_at timestamptz,
              promotion_mode text not null default 'auto',
              superseded_by_id uuid references public.artifact(id)
            );
            """
        )
    )
    db.connection().execute(
        text(
            """
            create table if not exists public.execution_artifact_link (
              execution_id uuid not null references public.execution(id) on delete cascade,
              artifact_id uuid not null references public.artifact(id) on delete cascade,
              relation text not null,
              created_at timestamptz not null default now(),
              primary key (execution_id, artifact_id, relation)
            );
            """
        )
    )
    db.commit()


def test_runs_start_events_and_memory_links(client, normal_user_token_headers, superuser_token_headers, db: Session) -> None:
    _ensure_memory_tables(db)

    payload = {
        "thread": {
            "title": "Delete item 11111111-1111-1111-1111-111111111111",
            "workflow_key": "customer_data_cleanup",
            "intent_key": "delete_item",
            "risk_level": "high",
            "status": "done",
            "systems_touched": {"endpoint": "/api/v1/items/{id}"},
        },
        "execution": {
            "targets": [{"entity": "item", "id": "11111111-1111-1111-1111-111111111111"}],
            "status": "running",
        },
        "reuse_within_seconds": 60 * 60 * 24 * 365,
    }

    res1 = client.post("/api/v1/executions/start", headers=normal_user_token_headers, json=payload)
    assert res1.status_code == 201, res1.text
    body1 = res1.json()
    assert body1["reused_thread"] is False
    thread_id = body1["thread"]["id"]
    execution1_id = body1["execution"]["id"]

    payload2 = dict(payload)
    payload2["thread"] = dict(payload["thread"])
    payload2["thread"]["title"] = "Delete item 22222222-2222-2222-2222-222222222222"
    payload2["execution"] = {"targets": [{"entity": "item", "id": "22222222-2222-2222-2222-222222222222"}]}

    res2 = client.post("/api/v1/executions/start", headers=normal_user_token_headers, json=payload2)
    assert res2.status_code == 201, res2.text
    body2 = res2.json()
    assert body2["reused_thread"] is True
    assert body2["thread"]["id"] == thread_id
    execution2_id = body2["execution"]["id"]
    assert execution2_id != execution1_id

    # Events CRUD
    ev = client.post(
        f"/api/v1/executions/{execution1_id}/events",
        headers=normal_user_token_headers,
        json={"type": "cmd", "message": "DELETE /api/v1/items/<id>", "data": {"ok": True}},
    )
    assert ev.status_code == 201, ev.text
    event_id = ev.json()["id"]

    ev_list = client.get(f"/api/v1/executions/{execution1_id}/events", headers=normal_user_token_headers)
    assert ev_list.status_code == 200, ev_list.text
    assert ev_list.json()["count"] >= 1

    ev_del = client.delete(
        f"/api/v1/executions/{execution1_id}/events/{event_id}",
        headers=superuser_token_headers,
    )
    assert ev_del.status_code == 200, ev_del.text

    # Artifact link CRUD
    li_id = uuid.uuid4()
    db.connection().execute(
        text(
            "insert into public.artifact (id, workflow_key, kind, title, body_mdc) "
            "values (:id, :workflow_key, :kind, :title, :body_mdc)"
        ),
        {
            "id": li_id,
            "workflow_key": "customer_data_cleanup",
            "kind": "checklist",
            "title": "Delete item (audit)",
            "body_mdc": "Audit log",
        },
    )
    db.commit()

    link = client.post(
        f"/api/v1/executions/{execution1_id}/artifact-links",
        headers=normal_user_token_headers,
        json={"artifact_id": str(li_id), "relation": "used"},
    )
    assert link.status_code == 201, link.text
    assert link.json()["artifact"]["id"] == str(li_id)

    links = client.get(f"/api/v1/executions/{execution1_id}/artifact-links", headers=normal_user_token_headers)
    assert links.status_code == 200, links.text
    assert links.json()["count"] >= 1

    unlink = client.delete(
        f"/api/v1/executions/{execution1_id}/artifact-links/{li_id}?relation=used",
        headers=superuser_token_headers,
    )
    assert unlink.status_code == 200, unlink.text

    # Cleanup
    db.connection().execute(text("delete from public.thread where id = :id"), {"id": thread_id})
    db.connection().execute(text("delete from public.artifact where id = :id"), {"id": li_id})
    db.commit()
