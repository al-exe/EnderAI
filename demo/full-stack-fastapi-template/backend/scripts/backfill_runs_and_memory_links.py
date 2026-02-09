#!/usr/bin/env python3
"""
Backfill Runs for existing Tasks that have none, and attach Library memory items to Runs.

This is intended for environments where:
- Tasks + Library items exist, but Runs were not created (or were created inconsistently).
- Library items may include `tags.task_id` so we can link them to a Run.

Safety goals:
- Idempotent: re-running should be a no-op once every Task has >=1 Run and memory links exist.
- Conservative linking: only links Library items that explicitly declare `tags.task_id`.

Notes:
- Uses the public HTTP API (requires `ENDERAI_BEARER_TOKEN`).
- Defaults to the deployed backend at https://enderai-backend.onrender.com.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable


DEFAULT_BASE_URL = "https://enderai-backend.onrender.com"
TOKEN_ENV = "ENDERAI_BEARER_TOKEN"

# Mirrors backend canonicalization in app/api/routes/runs.py when intent_key is missing.
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    flags=re.IGNORECASE,
)


def canonicalize_task_title(title: str) -> str:
    cleaned = _UUID_RE.sub("", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or title.strip()


def extract_uuids(text: str) -> list[str]:
    return _UUID_RE.findall(text or "")


@dataclass(frozen=True)
class ApiConfig:
    base_url: str
    token: str
    timeout_s: int = 30


class ApiError(RuntimeError):
    def __init__(self, method: str, url: str, status: int, body: str) -> None:
        super().__init__(f"{method} {url} -> {status}: {body[:500]}")
        self.method = method
        self.url = url
        self.status = status
        self.body = body


def _request(
    cfg: ApiConfig,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    retries: int = 3,
) -> Any:
    url = cfg.base_url.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})

    headers = {
        "Authorization": f"Bearer {cfg.token}",
        "Content-Type": "application/json",
    }
    data = None if body is None else json.dumps(body).encode("utf-8")

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=cfg.timeout_s) as r:
                payload = r.read().decode("utf-8") or "null"
                return json.loads(payload)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            raise ApiError(method, url, e.code, raw) from e
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt >= retries:
                raise
            time.sleep(0.25 * (2**attempt))
    raise RuntimeError("unreachable") from last_err


def paginate(cfg: ApiConfig, path: str, *, params: dict[str, Any] | None = None, limit: int = 200) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    skip = 0
    while True:
        p = dict(params or {})
        p.update({"skip": skip, "limit": limit})
        res = _request(cfg, "GET", path, params=p)
        batch = res.get("data") or []
        out.extend(batch)
        if len(batch) < limit:
            break
        skip += limit
    return out


def _merge_systems_touched(existing: dict[str, Any] | None, updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    for k, v in updates.items():
        if v is None:
            continue
        # Prefer not to clobber existing structured fields.
        if k not in merged:
            merged[k] = v
    return merged


def backfill(cfg: ApiConfig, *, dry_run: bool, workflow_key: str | None, max_tasks: int | None) -> int:
    tasks = paginate(cfg, "/api/v1/tasks/", params={"workflow_key": workflow_key} if workflow_key else None)
    runs = paginate(cfg, "/api/v1/runs/")
    library = paginate(cfg, "/api/v1/library/", params={"current_only": "false"})

    runs_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        runs_by_task[str(r["task_id"])].append(r)

    library_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for li in library:
        tid = (li.get("tags") or {}).get("task_id")
        if tid:
            library_by_task[str(tid)].append(li)

    # Deterministic ordering helps debug.
    tasks_sorted = sorted(tasks, key=lambda t: (t.get("workflow_key") or "", t.get("created_at") or "", t.get("id") or ""))

    created_runs = 0
    created_links = 0
    patched_titles = 0
    patched_details = 0
    restored_status = 0
    duplicate_group_skipped = 0
    collision_reused_other_task = 0
    skipped = 0
    failed = 0
    failures: list[tuple[str, str]] = []

    # When the deployed DB schema lacks intent_key, /runs/start groups by (workflow_key, canonicalized title).
    # Avoid creating multiple Runs for the same group, and avoid spurious failures when duplicate Task rows exist.
    handled_groups: set[tuple[str, str]] = set()

    for task in tasks_sorted:
        task_id = str(task["id"])
        if runs_by_task.get(task_id):
            skipped += 1
            continue

        if max_tasks is not None and created_runs >= max_tasks:
            break

        original_status = task.get("status") or "open"
        original_title = task.get("title") or ""
        workflow = task.get("workflow_key") or ""

        # Ensure /runs/start will reuse the existing Task in schemas without intent_key.
        canonical_title = canonicalize_task_title(original_title)
        uuids_in_title = extract_uuids(original_title)
        group_key = (workflow, canonical_title)
        if group_key in handled_groups:
            duplicate_group_skipped += 1
            continue

        try:
            if canonical_title != original_title.strip():
                # Patch title to match /runs/start grouping when intent_key is missing.
                systems_updates: dict[str, Any] = {}
                if uuids_in_title:
                    systems_updates["original_title"] = original_title
                    # Preserve the most likely target id for auditability.
                    systems_updates["target_id"] = uuids_in_title[0]

                if not dry_run:
                    merged_systems = _merge_systems_touched(task.get("systems_touched") or {}, systems_updates)
                    _request(
                        cfg,
                        "PATCH",
                        f"/api/v1/tasks/{task_id}",
                        body={"title": canonical_title, "systems_touched": merged_systems},
                    )
                task["title"] = canonical_title
                task["systems_touched"] = _merge_systems_touched(task.get("systems_touched") or {}, systems_updates)
                patched_titles += 1

            # Fill missing Task details (only when blank).
            goal = task.get("goal")
            ac = task.get("acceptance_criteria")
            systems = task.get("systems_touched") or {}
            if (not goal) or (not ac) or (not systems):
                mem = sorted(library_by_task.get(task_id, []), key=lambda li: li.get("created_at") or "")
                if not goal:
                    if mem:
                        goal = f"See linked memory: {mem[0].get('title')}"
                    else:
                        goal = task.get("title")
                if not ac:
                    if mem:
                        titles = [m.get("title") for m in mem if m.get("title")]
                        ac = "Linked memory items:\n- " + "\n- ".join(titles) if titles else None
                    else:
                        ac = "1) A Run exists for this Task.\n2) Any associated memory is linked to that Run."
                if not systems:
                    systems = {}
                # Merge in any useful tags from memory items, but only if keys are absent.
                for m in mem:
                    tags = m.get("tags") or {}
                    for k in ("repo", "branch", "commit", "provider", "runtime", "entity", "entity_id", "item_id", "owner_user_id"):
                        if k in tags and k not in systems:
                            systems[k] = tags[k]

                if not dry_run:
                    _request(
                        cfg,
                        "PATCH",
                        f"/api/v1/tasks/{task_id}",
                        body={"goal": goal, "acceptance_criteria": ac, "systems_touched": systems},
                    )
                patched_details += 1

            # Create the Run via /runs/start.
            targets: list[Any] = []
            if uuids_in_title:
                targets = [uuids_in_title[0]]

            run_summary = "Backfill: created missing Run for existing Task; original run details/events were not recorded."
            payload = {
                "task": {
                    "title": task.get("title") or original_title,
                    "workflow_key": workflow,
                },
                "run": {"targets": targets, "status": "success", "summary": run_summary},
                "reuse_within_seconds": None,
            }

            if dry_run:
                # Pretend a run was created; skip writes.
                created_runs += 1
                handled_groups.add(group_key)
                continue

            res = _request(cfg, "POST", "/api/v1/runs/start", body=payload)
            returned_task_id = str((res.get("task") or {}).get("id") or "")
            run_id = str((res.get("run") or {}).get("id") or "")
            if not run_id:
                raise RuntimeError(f"/runs/start returned no run.id for task_id={task_id}")
            handled_groups.add(group_key)

            created_runs += 1
            # Ensure ended_at gets populated for terminal statuses.
            _request(cfg, "PATCH", f"/api/v1/runs/{run_id}", body={"status": "success"})

            if returned_task_id != task_id:
                # This happens when duplicate Task rows exist for the same (workflow_key, title):
                # /runs/start will reuse whichever Task has the latest last_touched_at.
                collision_reused_other_task += 1
                runs_by_task.setdefault(returned_task_id, []).append({"id": run_id})
                # Don't attempt to attach memory or restore status to the wrong Task id.
                continue

            runs_by_task.setdefault(task_id, []).append({"id": run_id})

            # Restore Task status if /runs/start reopened a done Task.
            if original_status == "done":
                _request(cfg, "PATCH", f"/api/v1/tasks/{task_id}", body={"status": "done"})
                restored_status += 1

            # Attach any Library memory items that explicitly reference this Task.
            for li in sorted(library_by_task.get(task_id, []), key=lambda x: x.get("created_at") or ""):
                li_id = str(li["id"])
                created_at = li.get("created_at")
                _request(
                    cfg,
                    "POST",
                    f"/api/v1/runs/{run_id}/memory-links",
                    body={
                        "library_item_id": li_id,
                        "relation": "created",
                        "created_at": created_at,
                    },
                )
                created_links += 1

        except Exception:  # noqa: BLE001
            failed += 1
            failures.append((task_id, f"{workflow}: {original_title}"))
            continue

    print("Backfill summary")
    print("  tasks_total:", len(tasks))
    print("  tasks_skipped_has_runs:", skipped)
    print("  runs_created:", created_runs)
    print("  task_titles_canonicalized:", patched_titles)
    print("  tasks_details_patched:", patched_details)
    print("  tasks_status_restored_done:", restored_status)
    print("  duplicate_group_skipped:", duplicate_group_skipped)
    print("  collisions_reused_other_task:", collision_reused_other_task)
    print("  memory_links_created:", created_links)
    print("  tasks_failed:", failed)
    if failures:
        print("  failed_task_ids:")
        for tid, desc in failures[:20]:
            print("   -", tid, desc)

    # Exit non-zero on failures so callers can notice.
    return 0 if failed == 0 else 2


def main(argv: Iterable[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=os.environ.get("ENDERAI_BASE_URL") or DEFAULT_BASE_URL)
    p.add_argument("--workflow-key", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-tasks", type=int, default=None)
    args = p.parse_args(list(argv))

    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"ERROR: missing {TOKEN_ENV}", file=sys.stderr)
        return 2

    cfg = ApiConfig(base_url=args.base_url, token=token)
    return backfill(cfg, dry_run=args.dry_run, workflow_key=args.workflow_key, max_tasks=args.max_tasks)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
