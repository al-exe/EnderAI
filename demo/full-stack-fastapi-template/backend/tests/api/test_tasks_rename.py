import uuid

from sqlalchemy import text
from sqlmodel import Session


def _ensure_task_table(db: Session) -> None:
    db.connection().execute(
        text(
            """
            create table if not exists public.task (
              id uuid primary key,
              title text not null,
              workflow_key text not null,
              goal text null,
              acceptance_criteria text null,
              systems_touched jsonb not null default '{}'::jsonb,
              risk_level text not null default 'read_only',
              status text not null default 'open',
              created_at timestamptz not null default now(),
              last_touched_at timestamptz not null default now()
            )
            """
        )
    )
    db.commit()


def test_patch_task_title_persists(client, normal_user_token_headers, db: Session) -> None:
    _ensure_task_table(db)

    task_id = uuid.uuid4()
    db.connection().execute(
        text(
            "insert into public.task (id, title, workflow_key) "
            "values (:id, :title, :workflow_key)"
        ),
        {"id": task_id, "title": "Old title", "workflow_key": "tasks_demo"},
    )
    db.commit()

    res = client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=normal_user_token_headers,
        json={"title": "New title"},
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["id"] == str(task_id)
    assert payload["title"] == "New title"

    persisted = (
        db.connection()
        .execute(text("select title from public.task where id = :id"), {"id": task_id})
        .scalar_one()
    )
    assert persisted == "New title"

    db.connection().execute(text("delete from public.task where id = :id"), {"id": task_id})
    db.commit()
