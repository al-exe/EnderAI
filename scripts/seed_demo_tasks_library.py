#!/usr/bin/env python3
"""
Seed the Tasks/Library schema with a retroactive "as-if we used it" history.

This is intended for the YC demo: show Run 1 creating memory, Run 2 utilizing it.

Connection info is read from either:
  - DATABASE_URL (preferred), or
  - PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD

Important: This script never writes secrets into the DB. Pass credentials via env.
"""

from __future__ import annotations

import argparse
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg2
import psycopg2.extras


def utc_dt(iso: str) -> datetime:
    # iso like "2026-02-03 09:01:00"
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


SEED_NS = uuid.uuid5(uuid.NAMESPACE_URL, "enderai-demo-seed-v1")


def seeded_uuid(key: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NS, key)


def _dsn_from_env() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    required = ["PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise SystemExit(
            "Missing env vars. Set DATABASE_URL or: "
            + ", ".join(missing)
        )

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
    # Idempotent insert using a per-event seed key stored in JSON.
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
        insert into public.run_event (
          run_id, ts, type, message, data
        ) values (
          %s, %s, %s, %s, %s::jsonb
        )
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


def humanize_workflow_key(workflow_key: str) -> str:
    parts = workflow_key.strip().split("_")
    words: list[str] = []
    for part in parts:
        lower = part.lower()
        if lower == "github":
            words.append("GitHub")
        elif lower == "api":
            words.append("API")
        elif lower == "db":
            words.append("DB")
        else:
            words.append(part.capitalize())
    return " ".join(words) if words else workflow_key


def upsert_workflow_bucket(cur, *, workflow_key: str, bucket_name: str) -> None:
    cur.execute(
        """
        insert into public.workflow_bucket (workflow_key, bucket_name)
        values (%s, %s)
        on conflict (workflow_key) do update set
          bucket_name=excluded.bucket_name,
          updated_at=now()
        """,
        (workflow_key, bucket_name),
    )


def link_run_library(cur, *, run_id: uuid.UUID, library_item_id: uuid.UUID, relation: str, created_at: datetime) -> None:
    cur.execute(
        """
        insert into public.run_library_link (run_id, library_item_id, relation, created_at)
        values (%s, %s, %s, %s)
        on conflict do nothing
        """,
        (str(run_id), str(library_item_id), relation, created_at),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Validate seed plan without writing.")
    args = parser.parse_args()

    # Seed IDs (deterministic).
    t_cleanup = seeded_uuid("task:customer_data_cleanup")
    t_gh = seeded_uuid("task:github_issue_ops")
    t_tables = seeded_uuid("task:memory_tables_bootstrap")
    t_items = seeded_uuid("task:items_tab_evolution")

    # Library items
    li_db_connect = seeded_uuid("lib:customer_data_cleanup:db_connect_recipe")
    li_db_pitfall = seeded_uuid("lib:customer_data_cleanup:pgcli_libpq_pitfall")
    li_safe_delete = seeded_uuid("lib:customer_data_cleanup:safe_delete_checklist")
    li_gh_ops = seeded_uuid("lib:github_issue_ops:gh_issue_recipe")
    li_tables = seeded_uuid("lib:memory_tables_bootstrap:create_tables_recipe")
    li_items_ui = seeded_uuid("lib:items_tab:items_ui_recipe")
    li_items_crud = seeded_uuid("lib:items_tab:items_crud_wiring_recipe")

    now = datetime.now(timezone.utc)

    cleanup_task = {
        "id": str(t_cleanup),
        "title": "Customer Data Cleanup (Render Postgres)",
        "workflow_key": "customer_data_cleanup",
        "goal": "Given UUID targets from support, safely delete customer-owned objects and verify post-state.",
        "acceptance_criteria": (
            "- Targets removed\n"
            "- No unexpected dependents broken\n"
            "- Post-state verified\n"
            "- Audit trail recorded\n"
            "- Reusable memory captured in Library"
        ),
        "systems_touched": {"db": {"provider": "render", "name": "enderai"}, "app": "fastapi-demo"},
        "risk_level": "writes",
        "status": "done",
        "created_at": utc_dt("2026-02-03 08:58:00"),
        "last_touched_at": utc_dt("2026-02-03 09:08:00"),
    }

    gh_task = {
        "id": str(t_gh),
        "title": "GitHub Issue Ops (Frontend)",
        "workflow_key": "github_issue_ops",
        "goal": "List/view/delete a frontend issue as part of demo workflow hygiene.",
        "acceptance_criteria": "- Issue discovered\n- Description captured\n- Issue deleted",
        "systems_touched": {"github": {"repo": "al-exe/EnderAI-frontend"}},
        "risk_level": "external_side_effects",
        "status": "done",
        "created_at": utc_dt("2026-02-03 09:10:00"),
        "last_touched_at": utc_dt("2026-02-03 09:11:00"),
    }

    tables_task = {
        "id": str(t_tables),
        "title": "Create Tasks/Library Tables (DB Bootstrap)",
        "workflow_key": "memory_tables_bootstrap",
        "goal": "Create minimal Postgres schema for Tasks/Runs/Library and verify it exists.",
        "acceptance_criteria": "- Tables exist and are queryable",
        "systems_touched": {"db": {"provider": "render", "name": "enderai"}},
        "risk_level": "writes",
        "status": "done",
        "created_at": utc_dt("2026-02-04 06:23:00"),
        "last_touched_at": utc_dt("2026-02-04 06:26:00"),
    }

    items_task = {
        "id": str(t_items),
        "title": "Items Tab (Frontend + CRUD Wiring)",
        "workflow_key": "items_tab",
        "goal": "Build the Items tab UX and wire it to backend CRUD endpoints.",
        "acceptance_criteria": (
            "- Items list renders\n"
            "- Per-item actions menu works (Edit/Delete)\n"
            "- CRUD calls succeed via backend API\n"
            "- Memory captured for repeatable future work"
        ),
        "systems_touched": {
            "repos": ["al-exe/EnderAI-frontend", "al-exe/EnderAI"],
            "paths": [
                "/home/alexlee/dev/EnderAI-frontend/src/routes/_layout/items.tsx",
                "/home/alexlee/dev/EnderAI-frontend/src/components/Items/ItemActionsMenu.tsx",
                "/home/alexlee/dev/EnderAI/demo/full-stack-fastapi-template/backend/app/api/routes/items.py",
            ],
        },
        "risk_level": "read_only",
        "status": "done",
        "created_at": utc_dt("2026-02-01 22:30:00"),
        "last_touched_at": utc_dt("2026-02-01 23:25:00"),
    }

    # Runs (deterministic).
    r_cleanup_1 = seeded_uuid("run:customer_data_cleanup:1")
    r_cleanup_2 = seeded_uuid("run:customer_data_cleanup:2")
    r_cleanup_3 = seeded_uuid("run:customer_data_cleanup:3")
    r_gh_1 = seeded_uuid("run:github_issue_ops:1")
    r_tables_1 = seeded_uuid("run:memory_tables_bootstrap:1")
    r_items_1 = seeded_uuid("run:items_tab:1")
    r_items_2 = seeded_uuid("run:items_tab:2")

    runs: list[dict[str, Any]] = [
        {
            "id": str(r_cleanup_1),
            "task_id": str(t_cleanup),
            "targets": [],
            "started_at": utc_dt("2026-02-03 09:01:00"),
            "ended_at": utc_dt("2026-02-03 09:03:00"),
            "status": "success",
            "summary": "Established DB connectivity and ran a smoke test.",
        },
        {
            "id": str(r_cleanup_2),
            "task_id": str(t_cleanup),
            "targets": [],
            "started_at": utc_dt("2026-02-03 09:04:00"),
            "ended_at": utc_dt("2026-02-03 09:04:30"),
            "status": "success",
            "summary": "Listed tables and queried baseline users/items.",
        },
        {
            "id": str(r_cleanup_3),
            "task_id": str(t_cleanup),
            # The deleted user UUID from the real run; in the demo story these are customer object UUIDs.
            "targets": ["22400760-ddab-4fe7-9e83-364f9a5510a3"],
            "started_at": utc_dt("2026-02-03 09:07:00"),
            "ended_at": utc_dt("2026-02-03 09:08:00"),
            "status": "success",
            "summary": "Checked dependents, deleted target, verified post-state.",
        },
        {
            "id": str(r_gh_1),
            "task_id": str(t_gh),
            "targets": ["issue#5"],
            "started_at": utc_dt("2026-02-03 09:10:00"),
            "ended_at": utc_dt("2026-02-03 09:11:00"),
            "status": "success",
            "summary": "Listed archive issues, captured description, deleted issue.",
        },
        {
            "id": str(r_tables_1),
            "task_id": str(t_tables),
            "targets": ["task", "run", "run_event", "library_item", "run_library_link"],
            "started_at": utc_dt("2026-02-04 06:24:00"),
            "ended_at": utc_dt("2026-02-04 06:26:00"),
            "status": "success",
            "summary": "Created memory tables and verified they exist.",
        },
        {
            "id": str(r_items_1),
            "task_id": str(t_items),
            "targets": ["EnderAI-frontend:/items"],
            "started_at": utc_dt("2026-02-01 22:35:00"),
            "ended_at": utc_dt("2026-02-01 22:50:00"),
            "status": "success",
            "summary": "Added the baseline Items UI (table + actions menu) without wiring.",
        },
        {
            "id": str(r_items_2),
            "task_id": str(t_items),
            "targets": ["api:/items", "EnderAI-frontend:ItemsService"],
            "started_at": utc_dt("2026-02-01 23:05:00"),
            "ended_at": utc_dt("2026-02-01 23:25:00"),
            "status": "success",
            "summary": "Wired Items UI to backend CRUD API (read/create/update/delete).",
        },
    ]

    library_items: list[dict[str, Any]] = [
        {
            "id": str(li_db_connect),
            "workflow_key": "customer_data_cleanup",
            "kind": "recipe",
            "title": "Connect To Render Postgres (Queries + Writes)",
            "body_mdc": (
                "# Recipe — Connect To Render Postgres\\n\\n"
                "Goal: run safe, auditable SQL for support workflows.\\n\\n"
                "## Rules\\n"
                "- Do not store DB passwords in repo files or logs. Use env vars.\\n\\n"
                "## Options\\n"
                "### Option A: pgcli (interactive)\\n"
                "```sh\\n"
                "PGPASSWORD=\"$PGPASSWORD\" pgcli -h \"$PGHOST\" -p \"$PGPORT\" -U \"$PGUSER\" \"$PGDATABASE\"\\n"
                "```\\n\\n"
                "### Option B: Python (non-interactive)\\n"
                "- Use psycopg2 for quick scripts; print only non-sensitive outputs.\\n\\n"
                "## Verify\\n"
                "- `select now();`\\n"
                "- list tables via `information_schema.tables`\\n"
            ),
            "tags": {"scope": "db", "provider": "render"},
            "source_refs": [
                "architecture/3-task-context/flight-logs/2026-02-03.mdc",
            ],
            "created_at": utc_dt("2026-02-03 09:02:00"),
            "last_used_at": utc_dt("2026-02-04 06:26:00"),  # used again during table creation/verification
            "promotion_mode": "auto",
            "superseded_by_id": None,
        },
        {
            "id": str(li_db_pitfall),
            "workflow_key": "customer_data_cleanup",
            "kind": "pitfall",
            "title": "pgcli Fails Without libpq (Install psycopg-binary)",
            "body_mdc": (
                "# Pitfall — pgcli ImportError (libpq missing)\\n\\n"
                "Symptom: pgcli crashes with an ImportError about no pq wrapper / libpq not found.\\n\\n"
                "Fix (venv):\\n"
                "```sh\\n"
                "pip install \"psycopg[binary]\"\\n"
                "```\\n\\n"
                "Verify:\\n"
                "- `pgcli --help` works\\n"
            ),
            "tags": {"scope": "local_dev", "tool": "pgcli"},
            "source_refs": [
                "architecture/3-task-context/flight-logs/2026-02-03.mdc",
            ],
            "created_at": utc_dt("2026-02-03 09:02:30"),
            "last_used_at": utc_dt("2026-02-03 09:03:00"),
            "promotion_mode": "auto",
            "superseded_by_id": None,
        },
        {
            "id": str(li_safe_delete),
            "workflow_key": "customer_data_cleanup",
            "kind": "checklist",
            "title": "Safe Delete Workflow (Verify Dependents + Post-State)",
            "body_mdc": (
                "# Checklist — Safe Delete\\n\\n"
                "## Steps\\n"
                "1) Verify target exists (by UUID/email/etc).\\n"
                "2) Check dependents (count references).\\n"
                "3) Delete with `returning` to confirm what was removed.\\n"
                "4) Verify post-state (re-query).\\n"
                "5) Record evidence (SQL + outputs) and mark BREAKTHROUGH if applicable.\\n\\n"
                "## Notes\\n"
                "- Never delete memory; supersede when rules change.\\n"
            ),
            "tags": {"scope": "db", "operation": "delete"},
            "source_refs": [
                "architecture/3-task-context/flight-logs/2026-02-03.mdc",
            ],
            "created_at": utc_dt("2026-02-03 09:07:00"),
            "last_used_at": utc_dt("2026-02-03 09:08:00"),
            "promotion_mode": "auto",
            "superseded_by_id": None,
        },
        {
            "id": str(li_gh_ops),
            "workflow_key": "github_issue_ops",
            "kind": "recipe",
            "title": "GitHub Issue Ops (List/View/Delete)",
            "body_mdc": (
                "# Recipe — GitHub Issue Ops\\n\\n"
                "## List\\n"
                "```sh\\n"
                "gh issue list -R <owner/repo> -S \"archive\"\\n"
                "```\\n\\n"
                "## View\\n"
                "```sh\\n"
                "gh issue view <num> -R <owner/repo> --json title,body,createdAt,state\\n"
                "```\\n\\n"
                "## Delete (destructive)\\n"
                "```sh\\n"
                "gh issue delete <num> -R <owner/repo> --yes\\n"
                "```\\n"
            ),
            "tags": {"scope": "github"},
            "source_refs": [
                "architecture/3-task-context/flight-logs/2026-02-03.mdc",
            ],
            "created_at": utc_dt("2026-02-03 09:11:00"),
            "last_used_at": utc_dt("2026-02-03 09:11:00"),
            "promotion_mode": "auto",
            "superseded_by_id": None,
        },
        {
            "id": str(li_tables),
            "workflow_key": "memory_tables_bootstrap",
            "kind": "recipe",
            "title": "Create Memory Tables (Tasks/Runs/Library)",
            "body_mdc": (
                "# Recipe — Create Memory Tables\\n\\n"
                "```sh\\n"
                "DATABASE_URL=\"$DATABASE_URL\" python scripts/create_memory_tables.py\\n"
                "```\\n\\n"
                "Verify:\\n"
                "- `task`, `run`, `run_event`, `library_item`, `run_library_link` exist\\n"
            ),
            "tags": {"scope": "db", "schema": "memory"},
            "source_refs": [
                "scripts/create_memory_tables.py",
                "architecture/3-task-context/flight-logs/2026-02-04.mdc",
            ],
            "created_at": utc_dt("2026-02-04 06:24:00"),
            "last_used_at": utc_dt("2026-02-04 06:26:00"),
            "promotion_mode": "auto",
            "superseded_by_id": None,
        },
        {
            "id": str(li_items_ui),
            "workflow_key": "items_tab",
            "kind": "recipe",
            "title": "Items UI (Route + Table + Actions Menu)",
            "body_mdc": (
                "# Recipe — Items UI (Route + Table + Actions Menu)\\n\\n"
                "Goal: understand how the Items list renders and how the per-item dropdown opens Edit/Delete modals.\\n\\n"
                "## Frontend location\\n"
                "- Repo: `/home/alexlee/dev/EnderAI-frontend`\\n"
                "- Route: `src/routes/_layout/items.tsx`\\n\\n"
                "## Table rendering\\n"
                "- Uses `ItemsService.readItems({ skip: 0, limit: 100 })` and renders a shared `DataTable`.\\n"
                "- Table columns live in: `src/components/Items/columns.tsx`\\n\\n"
                "## Actions dropdown + modals\\n"
                "- Dropdown trigger per row: `src/components/Items/ItemActionsMenu.tsx`\\n"
                "- Menu entries are `DropdownMenuItem`s that open dialogs:\\n"
                "  - Edit modal: `src/components/Items/EditItem.tsx`\\n"
                "  - Delete confirmation modal: `src/components/Items/DeleteItem.tsx`\\n\\n"
                "Notes:\\n"
                "- Each action owns its own `Dialog open` state.\\n"
                "- After success, Items query is invalidated with `queryKey: ['items']`.\\n"
            ),
            "tags": {"area": "frontend", "feature": "items"},
            "source_refs": [
                "/home/alexlee/dev/EnderAI-frontend/src/routes/_layout/items.tsx",
                "/home/alexlee/dev/EnderAI-frontend/src/components/Items/columns.tsx",
                "/home/alexlee/dev/EnderAI-frontend/src/components/Items/ItemActionsMenu.tsx",
                "/home/alexlee/dev/EnderAI-frontend/src/components/Items/EditItem.tsx",
                "/home/alexlee/dev/EnderAI-frontend/src/components/Items/DeleteItem.tsx",
            ],
            "created_at": utc_dt("2026-02-01 22:50:00"),
            "last_used_at": utc_dt("2026-02-01 23:05:00"),
            "promotion_mode": "auto",
            "superseded_by_id": None,
        },
        {
            "id": str(li_items_crud),
            "workflow_key": "items_tab",
            "kind": "recipe",
            "title": "Items CRUD Wiring (Backend API + Frontend Client)",
            "body_mdc": (
                "# Recipe — Items CRUD Wiring\\n\\n"
                "Goal: wire the Items UI to backend CRUD endpoints and verify the list refreshes correctly.\\n\\n"
                "## Backend\\n"
                "- FastAPI routes: `demo/full-stack-fastapi-template/backend/app/api/routes/items.py`\\n"
                "- DB table: `public.item` (model: `demo/full-stack-fastapi-template/backend/app/models.py` → `Item`)\\n"
                "- Endpoints (auth required):\\n"
                "  - `GET /api/v1/items/`\\n"
                "  - `POST /api/v1/items/`\\n"
                "  - `PUT /api/v1/items/{id}`\\n"
                "  - `DELETE /api/v1/items/{id}`\\n\\n"
                "## Frontend\\n"
                "- Generated client lives under: `src/client/`\\n"
                "- Items calls are in `ItemsService` (imported from `@/client`).\\n"
                "- Items list query lives in: `src/routes/_layout/items.tsx` (queryKey: `['items']`).\\n\\n"
                "## Verify\\n"
                "- Create an item -> list updates (query invalidation).\\n"
                "- Edit an item -> list updates.\\n"
                "- Delete an item -> list updates.\\n"
            ),
            "tags": {"area": "full_stack", "feature": "items"},
            "source_refs": [
                "/home/alexlee/dev/EnderAI/demo/full-stack-fastapi-template/backend/app/api/routes/items.py",
                "/home/alexlee/dev/EnderAI/demo/full-stack-fastapi-template/backend/app/models.py",
                "/home/alexlee/dev/EnderAI-frontend/src/routes/_layout/items.tsx",
                "/home/alexlee/dev/EnderAI-frontend/src/client/sdk.gen.ts",
            ],
            "created_at": utc_dt("2026-02-01 23:25:00"),
            "last_used_at": utc_dt("2026-02-01 23:25:00"),
            "promotion_mode": "auto",
            "superseded_by_id": None,
        },
    ]

    # Run events: key timeline only (no secrets).
    events: list[tuple[uuid.UUID, str, datetime, str, str | None, dict[str, Any] | None]] = [
        (
            r_cleanup_1,
            "seed:cleanup:1:note",
            utc_dt("2026-02-03 09:01:00"),
            "note",
            "Request: set up DB access so EnderAI can query Render Postgres.",
            {"workflow_key": "customer_data_cleanup"},
        ),
        (
            r_cleanup_1,
            "seed:cleanup:1:error_psql",
            utc_dt("2026-02-03 09:01:30"),
            "error",
            "`psql` not available in environment (command not found).",
            {"tool": "psql"},
        ),
        (
            r_cleanup_1,
            "seed:cleanup:1:workaround_pgcli",
            utc_dt("2026-02-03 09:02:00"),
            "cmd",
            "Workaround: use a Python venv + pgcli for interactive DB access (no sudo).",
            {"tool": "pgcli"},
        ),
        (
            r_cleanup_1,
            "seed:cleanup:1:breakthrough",
            utc_dt("2026-02-03 09:03:00"),
            "breakthrough",
            "BREAKTHROUGH: Connected to Render Postgres and completed smoke test.",
            {"result": "inserted row + select count ok"},
        ),
        (
            r_cleanup_2,
            "seed:cleanup:2:list_tables",
            utc_dt("2026-02-03 09:04:00"),
            "sql",
            "Listed tables in public schema.",
            {"tables": ["public.alembic_version", "public.item", "public.user"]},
        ),
        (
            r_cleanup_2,
            "seed:cleanup:2:query_users_items",
            utc_dt("2026-02-03 09:04:20"),
            "sql",
            "Queried baseline users/items for demo verification.",
            {
                "users_count": 2,
                "items_count": 5,
                "note": "outputs intentionally summarized; no secrets stored",
            },
        ),
        (
            r_cleanup_3,
            "seed:cleanup:3:dependents_check",
            utc_dt("2026-02-03 09:07:00"),
            "sql",
            "Checked dependents for target before delete.",
            {"email": "alexl@gmail.com", "dependent_items": 0},
        ),
        (
            r_cleanup_3,
            "seed:cleanup:3:delete",
            utc_dt("2026-02-03 09:07:30"),
            "sql",
            "Deleted target user (no dependents).",
            {"email": "alexl@gmail.com", "deleted_user_id": "22400760-ddab-4fe7-9e83-364f9a5510a3"},
        ),
        (
            r_cleanup_3,
            "seed:cleanup:3:verify",
            utc_dt("2026-02-03 09:08:00"),
            "sql",
            "Verified post-state (user removed; remaining items intact).",
            {"remaining_users": 1, "remaining_items": 5},
        ),
        (
            r_gh_1,
            "seed:gh:1:list",
            utc_dt("2026-02-03 09:10:00"),
            "cmd",
            "Listed frontend issues matching 'archive'.",
            {"repo": "al-exe/EnderAI-frontend", "found": ["#5 [Feature] Archived items list UI"]},
        ),
        (
            r_gh_1,
            "seed:gh:1:view",
            utc_dt("2026-02-03 09:11:00"),
            "cmd",
            "Captured issue #5 description (context/requirements/acceptance).",
            {"issue": 5},
        ),
        (
            r_gh_1,
            "seed:gh:1:delete",
            utc_dt("2026-02-03 09:11:10"),
            "cmd",
            "Deleted issue #5 after capturing description.",
            {"issue": 5, "destructive": True},
        ),
        (
            r_tables_1,
            "seed:tables:1:apply",
            utc_dt("2026-02-04 06:25:00"),
            "cmd",
            "Ran create_memory_tables.py to create Tasks/Library tables (create-if-not-exists).",
            {"script": "scripts/create_memory_tables.py"},
        ),
        (
            r_tables_1,
            "seed:tables:1:verify",
            utc_dt("2026-02-04 06:26:00"),
            "sql",
            "Verified memory tables exist via information_schema.",
            {"tables": ["task", "run", "run_event", "library_item", "run_library_link"]},
        ),
        (
            r_items_1,
            "seed:items:1:note",
            utc_dt("2026-02-01 22:36:00"),
            "note",
            "Built baseline Items UI: Items route + DataTable + per-item actions dropdown.",
            {
                "files": [
                    "/home/alexlee/dev/EnderAI-frontend/src/routes/_layout/items.tsx",
                    "/home/alexlee/dev/EnderAI-frontend/src/components/Items/columns.tsx",
                    "/home/alexlee/dev/EnderAI-frontend/src/components/Items/ItemActionsMenu.tsx",
                ]
            },
        ),
        (
            r_items_1,
            "seed:items:1:breakthrough",
            utc_dt("2026-02-01 22:50:00"),
            "breakthrough",
            "BREAKTHROUGH: Items table renders with per-row actions dropdown (Edit/Delete).",
            {"route": "/items"},
        ),
        (
            r_items_2,
            "seed:items:2:note",
            utc_dt("2026-02-01 23:06:00"),
            "note",
            "Wired Items UI to backend CRUD endpoints via ItemsService; ensured list refreshes via query invalidation.",
            {
                "backend": "demo/full-stack-fastapi-template/backend/app/api/routes/items.py",
                "frontend": "/home/alexlee/dev/EnderAI-frontend/src/routes/_layout/items.tsx",
            },
        ),
        (
            r_items_2,
            "seed:items:2:verify",
            utc_dt("2026-02-01 23:24:00"),
            "note",
            "Verified create/edit/delete flows update the list (queryKey: ['items']).",
            {"query_key": ["items"]},
        ),
    ]

    # Run -> library links (Created vs Utilized story).
    links: list[tuple[uuid.UUID, uuid.UUID, str, datetime]] = [
        # Cleanup run 1: created + promoted core DB connectivity memory.
        (r_cleanup_1, li_db_connect, "created", utc_dt("2026-02-03 09:03:00")),
        (r_cleanup_1, li_db_connect, "promoted", utc_dt("2026-02-03 09:03:00")),
        (r_cleanup_1, li_db_pitfall, "created", utc_dt("2026-02-03 09:03:00")),
        (r_cleanup_1, li_db_pitfall, "promoted", utc_dt("2026-02-03 09:03:00")),
        # Cleanup run 2: utilized DB connect memory.
        (r_cleanup_2, li_db_connect, "used", utc_dt("2026-02-03 09:04:00")),
        (r_cleanup_2, li_db_pitfall, "used", utc_dt("2026-02-03 09:04:00")),
        # Cleanup run 3: utilized DB connect, created/promoted safe delete checklist.
        (r_cleanup_3, li_db_connect, "used", utc_dt("2026-02-03 09:07:00")),
        (r_cleanup_3, li_safe_delete, "created", utc_dt("2026-02-03 09:08:00")),
        (r_cleanup_3, li_safe_delete, "promoted", utc_dt("2026-02-03 09:08:00")),
        (r_cleanup_3, li_safe_delete, "used", utc_dt("2026-02-03 09:07:00")),
        # GH ops: created/promoted recipe.
        (r_gh_1, li_gh_ops, "created", utc_dt("2026-02-03 09:11:00")),
        (r_gh_1, li_gh_ops, "promoted", utc_dt("2026-02-03 09:11:00")),
        # Tables bootstrap: used DB connect recipe, created/promoted tables recipe.
        (r_tables_1, li_db_connect, "used", utc_dt("2026-02-04 06:25:00")),
        (r_tables_1, li_tables, "created", utc_dt("2026-02-04 06:26:00")),
        (r_tables_1, li_tables, "promoted", utc_dt("2026-02-04 06:26:00")),
        # Items tab run 1: created/promoted baseline UI recipe.
        (r_items_1, li_items_ui, "created", utc_dt("2026-02-01 22:50:00")),
        (r_items_1, li_items_ui, "promoted", utc_dt("2026-02-01 22:50:00")),
        # Items tab run 2: used baseline UI recipe; created/promoted CRUD wiring recipe.
        (r_items_2, li_items_ui, "used", utc_dt("2026-02-01 23:05:00")),
        (r_items_2, li_items_crud, "created", utc_dt("2026-02-01 23:25:00")),
        (r_items_2, li_items_crud, "promoted", utc_dt("2026-02-01 23:25:00")),
    ]

    if args.dry_run:
        print("Dry run OK. Would seed:")
        print(
            f"- tasks: 4 (cleanup={t_cleanup}, gh={t_gh}, tables={t_tables}, items={t_items})"
        )
        print(f"- runs: {len(runs)}")
        print(f"- run events: {len(events)}")
        print(f"- library items: {len(library_items)}")
        print(f"- run_library_link rows: {len(links)}")
        return 0

    dsn = _dsn_from_env()
    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            upsert_task(cur, cleanup_task)
            upsert_task(cur, gh_task)
            upsert_task(cur, tables_task)
            upsert_task(cur, items_task)

            for r in runs:
                upsert_run(cur, r)

            for li in library_items:
                upsert_workflow_bucket(
                    cur,
                    workflow_key=li["workflow_key"],
                    bucket_name=humanize_workflow_key(li["workflow_key"]),
                )

            for li in library_items:
                upsert_library_item(cur, li)

            for run_id, seed_key, ts, type_, message, data in events:
                ensure_run_event(
                    cur,
                    run_id=run_id,
                    seed_key=seed_key,
                    ts=ts,
                    type_=type_,
                    message=message,
                    data=data,
                )

            for run_id, library_item_id, relation, created_at in links:
                link_run_library(
                    cur,
                    run_id=run_id,
                    library_item_id=library_item_id,
                    relation=relation,
                    created_at=created_at,
                )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("OK: seeded Tasks/Runs/Library demo data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
