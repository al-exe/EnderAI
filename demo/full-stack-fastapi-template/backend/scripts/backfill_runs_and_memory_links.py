#!/usr/bin/env python3
"""
Backfill Executions for existing Threads that have none, and attach Artifacts to Executions.

This is intended for environments where:
- Threads + Artifacts exist, but Executions were not created (or were created inconsistently).
- Artifacts may include `tags.thread_id` so we can link them to an Execution.

Safety goals:
- Idempotent: re-running should be a no-op once every Thread has >=1 Execution and links exist.
- Conservative linking: only links Artifacts that explicitly declare `tags.thread_id`.

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


def canonicalize_thread_title(title: str) -> str:
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


def backfill(cfg: ApiConfig, *, dry_run: bool, workflow_key: str | None, max_threads: int | None) -> int:
    threads = paginate(cfg, "/api/v1/threads/", params={"workflow_key": workflow_key} if workflow_key else None)
    executions = paginate(cfg, "/api/v1/executions/")
    artifacts = paginate(cfg, "/api/v1/artifacts/", params={"current_only": "false"})

    executions_by_thread: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in executions:
        executions_by_thread[str(e["thread_id"])].append(e)

    artifacts_by_thread: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in artifacts:
        tags = a.get("tags") or {}
        tid = tags.get("thread_id") or tags.get("task_id")
        if tid:
            artifacts_by_thread[str(tid)].append(a)

    # Deterministic ordering helps debug.
    threads_sorted = sorted(threads, key=lambda t: (t.get("workflow_key") or "", t.get("created_at") or "", t.get("id") or ""))

    created_executions = 0
    created_links = 0
    patched_titles = 0
    patched_details = 0
    restored_status = 0
    duplicate_group_skipped = 0
    collision_reused_other_task = 0
    skipped = 0
    failed = 0
    failures: list[tuple[str, str]] = []

    # When the deployed DB schema lacks intent_key, /executions/start groups by (workflow_key, canonicalized title).
    # Avoid creating multiple Executions for the same group, and avoid spurious failures when duplicate Thread rows exist.
    handled_groups: set[tuple[str, str]] = set()

    for thread in threads_sorted:
        thread_id = str(thread["id"])
        if executions_by_thread.get(thread_id):
            skipped += 1
            continue

        if max_threads is not None and created_executions >= max_threads:
            break

        original_status = thread.get("status") or "open"
        original_title = thread.get("title") or ""
        workflow = thread.get("workflow_key") or ""

        # Ensure /executions/start will reuse the existing Thread in schemas without intent_key.
        canonical_title = canonicalize_thread_title(original_title)
        uuids_in_title = extract_uuids(original_title)
        group_key = (workflow, canonical_title)
        if group_key in handled_groups:
            duplicate_group_skipped += 1
            continue

        try:
            if canonical_title != original_title.strip():
                # Patch title to match /executions/start grouping when intent_key is missing.
                systems_updates: dict[str, Any] = {}
                if uuids_in_title:
                    systems_updates["original_title"] = original_title
                    # Preserve the most likely target id for auditability.
                    systems_updates["target_id"] = uuids_in_title[0]

                if not dry_run:
                    merged_systems = _merge_systems_touched(thread.get("systems_touched") or {}, systems_updates)
                    _request(
                        cfg,
                        "PATCH",
                        f"/api/v1/threads/{thread_id}",
                        body={"title": canonical_title, "systems_touched": merged_systems},
                    )
                thread["title"] = canonical_title
                thread["systems_touched"] = _merge_systems_touched(thread.get("systems_touched") or {}, systems_updates)
                patched_titles += 1

            # Fill missing Thread details (only when blank).
            goal = thread.get("goal")
            ac = thread.get("acceptance_criteria")
            systems = thread.get("systems_touched") or {}
            if (not goal) or (not ac) or (not systems):
                mem = sorted(artifacts_by_thread.get(thread_id, []), key=lambda li: li.get("created_at") or "")
                if not goal:
                    if mem:
                        goal = f"See linked memory: {mem[0].get('title')}"
                    else:
                        goal = thread.get("title")
                if not ac:
                    if mem:
                        titles = [m.get("title") for m in mem if m.get("title")]
                        ac = "Linked memory items:\n- " + "\n- ".join(titles) if titles else None
                    else:
                        ac = "1) An Execution exists for this Thread.\n2) Any associated Artifacts are linked."
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
                        f"/api/v1/threads/{thread_id}",
                        body={"goal": goal, "acceptance_criteria": ac, "systems_touched": systems},
                    )
                patched_details += 1

            # Create the Execution via /executions/start.
            targets: list[Any] = []
            if uuids_in_title:
                targets = [uuids_in_title[0]]

            run_summary = "Backfill: created missing Execution for existing Thread; original details/events were not recorded."
            payload = {
                "thread": {
                    "title": thread.get("title") or original_title,
                    "workflow_key": workflow,
                },
                "execution": {"targets": targets, "status": "success", "summary": run_summary},
                "reuse_within_seconds": None,
            }

            if dry_run:
                # Pretend a run was created; skip writes.
                created_executions += 1
                handled_groups.add(group_key)
                continue

            res = _request(cfg, "POST", "/api/v1/executions/start", body=payload)
            returned_thread_id = str((res.get("thread") or {}).get("id") or "")
            execution_id = str((res.get("execution") or {}).get("id") or "")
            if not execution_id:
                raise RuntimeError(f"/executions/start returned no execution.id for thread_id={thread_id}")
            handled_groups.add(group_key)

            created_executions += 1
            # Ensure ended_at gets populated for terminal statuses.
            _request(cfg, "PATCH", f"/api/v1/executions/{execution_id}", body={"status": "success"})

            if returned_thread_id != thread_id:
                # This happens when duplicate Thread rows exist for the same (workflow_key, title):
                # /executions/start will reuse whichever Thread has the latest last_touched_at.
                collision_reused_other_task += 1
                executions_by_thread.setdefault(returned_thread_id, []).append({"id": execution_id})
                # Don't attempt to attach memory or restore status to the wrong Task id.
                continue

            executions_by_thread.setdefault(thread_id, []).append({"id": execution_id})

            # Restore Thread status if /executions/start reopened a done Thread.
            if original_status == "done":
                _request(cfg, "PATCH", f"/api/v1/threads/{thread_id}", body={"status": "done"})
                restored_status += 1

            # Attach any Artifacts that explicitly reference this Thread.
            for li in sorted(artifacts_by_thread.get(thread_id, []), key=lambda x: x.get("created_at") or ""):
                li_id = str(li["id"])
                created_at = li.get("created_at")
                _request(
                    cfg,
                    "POST",
                    f"/api/v1/executions/{execution_id}/artifact-links",
                    body={
                        "artifact_id": li_id,
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
    print("  threads_total:", len(threads))
    print("  threads_skipped_has_executions:", skipped)
    print("  executions_created:", created_executions)
    print("  thread_titles_canonicalized:", patched_titles)
    print("  threads_details_patched:", patched_details)
    print("  threads_status_restored_done:", restored_status)
    print("  duplicate_group_skipped:", duplicate_group_skipped)
    print("  collisions_reused_other_task:", collision_reused_other_task)
    print("  artifact_links_created:", created_links)
    print("  threads_failed:", failed)
    if failures:
        print("  failed_thread_ids:")
        for tid, desc in failures[:20]:
            print("   -", tid, desc)

    # Exit non-zero on failures so callers can notice.
    return 0 if failed == 0 else 2


def main(argv: Iterable[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=os.environ.get("ENDERAI_BASE_URL") or DEFAULT_BASE_URL)
    p.add_argument("--workflow-key", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-threads", type=int, default=None)
    args = p.parse_args(list(argv))

    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"ERROR: missing {TOKEN_ENV}", file=sys.stderr)
        return 2

    cfg = ApiConfig(base_url=args.base_url, token=token)
    return backfill(cfg, dry_run=args.dry_run, workflow_key=args.workflow_key, max_threads=args.max_threads)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
