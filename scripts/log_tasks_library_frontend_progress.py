#!/usr/bin/env python3
"""
Log app development progress into the Tasks/Runs/Library memory tables.

This script is intentionally conservative:
- Defaults to --dry-run (no writes)
- Uses deterministic UUIDs
- Uses append-only run_event inserts (idempotent via data.seed_key)
- Uses supersede semantics for library_item updates (never delete)

Connection info is read from either:
  - DATABASE_URL (preferred), or
  - PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD

No secrets are stored in-repo; pass creds via env vars.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import psycopg2
import psycopg2.extras


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


APPDEV_NS = uuid.uuid5(uuid.NAMESPACE_URL, "enderai-app-dev-log-v1")


def seeded_uuid(key: str) -> uuid.UUID:
    return uuid.uuid5(APPDEV_NS, key)


def content_uuid(*, workflow_key: str, title: str, body_mdc: str) -> uuid.UUID:
    digest = hashlib.sha256(body_mdc.encode("utf-8")).hexdigest()
    return seeded_uuid(f"lib:{workflow_key}:{title}:{digest}")


def _dsn_from_env() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    required = ["PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise SystemExit("Missing env vars. Set DATABASE_URL or: " + ", ".join(missing))

    return (
        f"host={os.environ['PGHOST']} "
        f"port={os.environ['PGPORT']} "
        f"dbname={os.environ['PGDATABASE']} "
        f"user={os.environ['PGUSER']} "
        f"password={os.environ['PGPASSWORD']}"
    )


def upsert_task(cur, row: dict[str, Any]) -> None:
    row = dict(row)
    row["systems_touched"] = psycopg2.extras.Json(row.get("systems_touched", {}))
    cur.execute(
        """
        insert into public.task (
          id, title, workflow_key, goal, acceptance_criteria,
          systems_touched, risk_level, status, created_at, last_touched_at
        ) values (
          %(id)s, %(title)s, %(workflow_key)s, %(goal)s, %(acceptance_criteria)s,
          %(systems_touched)s, %(risk_level)s, %(status)s, %(created_at)s, %(last_touched_at)s
        )
        on conflict (id) do update set
          title=excluded.title,
          workflow_key=excluded.workflow_key,
          goal=excluded.goal,
          acceptance_criteria=excluded.acceptance_criteria,
          systems_touched=excluded.systems_touched,
          risk_level=excluded.risk_level,
          status=excluded.status,
          created_at=excluded.created_at,
          last_touched_at=excluded.last_touched_at
        """,
        row,
    )


def upsert_run(cur, row: dict[str, Any]) -> None:
    row = dict(row)
    row["targets"] = psycopg2.extras.Json(row.get("targets", []))
    cur.execute(
        """
        insert into public.run (
          id, task_id, targets, started_at, ended_at, status, summary
        ) values (
          %(id)s, %(task_id)s, %(targets)s, %(started_at)s, %(ended_at)s, %(status)s, %(summary)s
        )
        on conflict (id) do update set
          task_id=excluded.task_id,
          targets=excluded.targets,
          started_at=excluded.started_at,
          ended_at=excluded.ended_at,
          status=excluded.status,
          summary=excluded.summary
        """,
        row,
    )


def ensure_run_event(
    cur,
    *,
    run_id: uuid.UUID,
    seed_key: str,
    ts: datetime,
    type_: str,
    message: str | None,
    data: dict[str, Any] | None = None,
) -> None:
    cur.execute(
        "select 1 from public.run_event where run_id=%s and data->>'seed_key'=%s limit 1",
        (str(run_id), seed_key),
    )
    if cur.fetchone() is not None:
        return

    payload = dict(data or {})
    payload["seed_key"] = seed_key

    cur.execute(
        """
        insert into public.run_event (run_id, ts, type, message, data)
        values (%s, %s, %s, %s, %s::jsonb)
        """,
        (str(run_id), ts, type_, message, psycopg2.extras.Json(payload)),
    )


def upsert_library_item(cur, row: dict[str, Any]) -> None:
    row = dict(row)
    row["tags"] = psycopg2.extras.Json(row.get("tags", {}))
    row["source_refs"] = psycopg2.extras.Json(row.get("source_refs", []))
    cur.execute(
        """
        insert into public.library_item (
          id, workflow_key, kind, title, body_mdc,
          tags, source_refs, created_at, last_used_at, promotion_mode, superseded_by_id
        ) values (
          %(id)s, %(workflow_key)s, %(kind)s, %(title)s, %(body_mdc)s,
          %(tags)s, %(source_refs)s, %(created_at)s, %(last_used_at)s, %(promotion_mode)s, %(superseded_by_id)s
        )
        on conflict (id) do update set
          workflow_key=excluded.workflow_key,
          kind=excluded.kind,
          title=excluded.title,
          body_mdc=excluded.body_mdc,
          tags=excluded.tags,
          source_refs=excluded.source_refs,
          created_at=excluded.created_at,
          last_used_at=excluded.last_used_at,
          promotion_mode=excluded.promotion_mode,
          superseded_by_id=excluded.superseded_by_id
        """,
        row,
    )


def set_library_item_superseded_by(cur, *, old_id: uuid.UUID, new_id: uuid.UUID) -> None:
    cur.execute(
        "update public.library_item set superseded_by_id=%s where id=%s and superseded_by_id is null",
        (str(new_id), str(old_id)),
    )


def link_run_library(
    cur,
    *,
    run_id: uuid.UUID,
    library_item_id: uuid.UUID,
    relation: str,
    created_at: datetime,
) -> None:
    cur.execute(
        """
        insert into public.run_library_link (run_id, library_item_id, relation, created_at)
        values (%s, %s, %s, %s)
        on conflict do nothing
        """,
        (str(run_id), str(library_item_id), relation, created_at),
    )


@dataclass(frozen=True)
class LibraryDraft:
    workflow_key: str
    kind: str
    title: str
    body_mdc: str
    tags: dict[str, Any]
    source_refs: list[str]
    promotion_mode: str = "auto"

    def id_for_body(self) -> uuid.UUID:
        return content_uuid(workflow_key=self.workflow_key, title=self.title, body_mdc=self.body_mdc)


def find_current_library_item(cur, *, workflow_key: str, title: str) -> dict[str, Any] | None:
    cur.execute(
        """
        select id, body_mdc
        from public.library_item
        where workflow_key=%s and title=%s and superseded_by_id is null
        order by created_at desc
        limit 1
        """,
        (workflow_key, title),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {"id": uuid.UUID(row[0]), "body_mdc": row[1]}


def _print_plan(title: str, lines: Iterable[str]) -> None:
    print(f"\n== {title} ==")
    for line in lines:
        print(f"- {line}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write to DB. Without this flag, the script is dry-run (read-only).",
    )
    parser.add_argument(
        "--workflow-key",
        default="tasks_library_memory",
        help="Workflow key bucket for this progress log.",
    )
    args = parser.parse_args()

    now = utcnow()

    workflow_key: str = args.workflow_key
    task_id = seeded_uuid(f"task:{workflow_key}:frontend_ui")
    run_id = seeded_uuid(f"run:{workflow_key}:frontend_sidebar_tabs")

    task = {
        "id": str(task_id),
        "title": "Tasks + Library UI (Frontend)",
        "workflow_key": workflow_key,
        "goal": "Build the frontend UX for Tasks and Library with an auditable Memory Diff experience.",
        "acceptance_criteria": "- Tasks tab exists\n- Library tab exists\n- Navigation works end-to-end",
        "systems_touched": {"repo": "/home/alexlee/dev/EnderAI-frontend"},
        "risk_level": "read_only",
        "status": "in_progress",
        "created_at": now,
        "last_touched_at": now,
    }

    run = {
        "id": str(run_id),
        "task_id": str(task_id),
        "targets": [],
        "started_at": now,
        "ended_at": now,
        "status": "success",
        "summary": "Add Tasks/Library sidebar tabs + placeholder routes.",
    }

    recipe_body = "\n".join(
        [
            "# Recipe — Add Tasks/Library Tabs (TanStack Router)\n",
            "Goal: add `Tasks` and `Library` tabs under the existing sidebar navigation.\n",
            "## Steps\n",
            "1) Update sidebar items in:\n",
            "   - `/home/alexlee/dev/EnderAI-frontend/src/components/Sidebar/AppSidebar.tsx`\n",
            "   - Add `Tasks` -> `/tasks` (icon: `ListTodo`)\n",
            "   - Add `Library` -> `/library` (icon: `Library`)\n",
            "2) Add file-based routes under the authenticated layout:\n",
            "   - `/home/alexlee/dev/EnderAI-frontend/src/routes/_layout/tasks.tsx`\n",
            "   - `/home/alexlee/dev/EnderAI-frontend/src/routes/_layout/library.tsx`\n",
            "3) Verify TypeScript:\n",
            "   - `npx tsc -p tsconfig.build.json --noEmit`\n",
            "## Notes\n",
            "- `src/routeTree.gen.ts` is updated by the TanStack Router tooling after adding routes.\n",
        ]
    ).strip() + "\n"

    pitfall_body = "\n".join(
        [
            "# Pitfall — Vite Build Requires Newer Node\n",
            "If you see Vite errors about Node version or `crypto.hash is not a function`, upgrade Node.\n",
            "## Symptom\n",
            "- `vite build` fails with a message requiring Node `20.19+` (Vite 7).\n",
            "## Fix\n",
            "- Use Node `20.19+` (or `22.12+`).\n",
            "- Or use `bun run dev` locally if your environment supports it.\n",
        ]
    ).strip() + "\n"

    drafts: list[LibraryDraft] = [
        LibraryDraft(
            workflow_key=workflow_key,
            kind="recipe",
            title="Add Tasks/Library sidebar tabs",
            body_mdc=recipe_body,
            tags={"area": "frontend", "feature": "tasks-library"},
            source_refs=[
                "/home/alexlee/dev/EnderAI-frontend/src/components/Sidebar/AppSidebar.tsx",
                "/home/alexlee/dev/EnderAI-frontend/src/routes/_layout/tasks.tsx",
                "/home/alexlee/dev/EnderAI-frontend/src/routes/_layout/library.tsx",
            ],
        ),
        LibraryDraft(
            workflow_key=workflow_key,
            kind="pitfall",
            title="Vite 7 requires Node 20.19+",
            body_mdc=pitfall_body,
            tags={"area": "frontend", "tooling": "vite"},
            source_refs=["/home/alexlee/dev/EnderAI-frontend/package.json"],
        ),
    ]

    _print_plan(
        "Plan",
        [
            f"task_id={task_id} workflow_key={workflow_key}",
            f"run_id={run_id} summary={run['summary']}",
            f"library_items={len(drafts)} (create or supersede as needed)",
            "run_events=links/commands/errors for this step",
            "mode=" + ("APPLY (writes)" if args.apply else "DRY-RUN (read-only)"),
        ],
    )

    dsn = _dsn_from_env()
    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            # Read current library state to decide create vs used vs supersede.
            actions: list[str] = []
            lib_plan: dict[str, tuple[str, uuid.UUID, uuid.UUID | None]] = {}
            # value tuple: (op, library_item_id, old_id_if_supersede)
            for draft in drafts:
                current = find_current_library_item(cur, workflow_key=draft.workflow_key, title=draft.title)
                new_id = draft.id_for_body()
                if current is None:
                    actions.append(f"create library_item '{draft.title}' id={new_id}")
                    lib_plan[draft.title] = ("create", new_id, None)
                    continue

                old_id = current["id"]
                if current["body_mdc"] == draft.body_mdc:
                    actions.append(f"reuse existing library_item '{draft.title}' id={old_id} (link as used)")
                    lib_plan[draft.title] = ("use", old_id, None)
                    continue

                actions.append(f"supersede library_item '{draft.title}' old_id={old_id} -> new_id={new_id}")
                lib_plan[draft.title] = ("supersede", new_id, old_id)

            _print_plan("Library Actions", actions)

            if not args.apply:
                conn.rollback()
                return 0

            # Writes
            upsert_task(cur, task)
            upsert_run(cur, run)

            # Run events (idempotent via seed_key stored in data JSON)
            ensure_run_event(
                cur,
                run_id=run_id,
                seed_key=f"{workflow_key}:frontend_sidebar_tabs:note",
                ts=now,
                type_="note",
                message="Added Tasks/Library tabs under the sidebar and created placeholder routes.",
                data={
                    "files": [
                        "/home/alexlee/dev/EnderAI-frontend/src/components/Sidebar/AppSidebar.tsx",
                        "/home/alexlee/dev/EnderAI-frontend/src/routes/_layout/tasks.tsx",
                        "/home/alexlee/dev/EnderAI-frontend/src/routes/_layout/library.tsx",
                    ]
                },
            )
            ensure_run_event(
                cur,
                run_id=run_id,
                seed_key=f"{workflow_key}:frontend_sidebar_tabs:cmd:tsc",
                ts=now,
                type_="cmd",
                message="npx tsc -p tsconfig.build.json --noEmit",
                data={"exit_code": 0},
            )
            ensure_run_event(
                cur,
                run_id=run_id,
                seed_key=f"{workflow_key}:frontend_sidebar_tabs:error:vite_node",
                ts=now,
                type_="error",
                message="npm run build failed due to Node version mismatch (Vite 7 requires Node 20.19+).",
                data={"node_version": "18.19.1"},
            )

            # Library items + links
            for draft in drafts:
                op, library_item_id, old_id = lib_plan[draft.title]
                if op in ("create", "supersede"):
                    upsert_library_item(
                        cur,
                        {
                            "id": str(library_item_id),
                            "workflow_key": draft.workflow_key,
                            "kind": draft.kind,
                            "title": draft.title,
                            "body_mdc": draft.body_mdc,
                            "tags": draft.tags,
                            "source_refs": draft.source_refs,
                            "created_at": now,
                            "last_used_at": None,
                            "promotion_mode": draft.promotion_mode,
                            "superseded_by_id": None,
                        },
                    )
                    link_run_library(cur, run_id=run_id, library_item_id=library_item_id, relation="created", created_at=now)
                    link_run_library(cur, run_id=run_id, library_item_id=library_item_id, relation="promoted", created_at=now)

                if op == "use":
                    link_run_library(cur, run_id=run_id, library_item_id=library_item_id, relation="used", created_at=now)

                if op == "supersede":
                    assert old_id is not None
                    set_library_item_superseded_by(cur, old_id=old_id, new_id=library_item_id)
                    link_run_library(cur, run_id=run_id, library_item_id=old_id, relation="superseded", created_at=now)

            conn.commit()
            print("OK: wrote task/run/events/library links.")
            return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
