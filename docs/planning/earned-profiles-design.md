# Earned Profiles — Design (TF-205 / C6)

*Design-only. No behavior change ships with this ticket. This is the spec for the build step that follows.*

## Where this sits

The Taskforce loop is **raw input → clean agent profiles → redropped in** (see `taskforce-pipeline-deep-dive.md`). Today the *middle arrow* — turning cleaned `V2Document`s into `AgentSpecialist` profiles — is done **by hand** (`core/agents/seed.py`, TF-198): every specialist is `created_from="seeded"` with hand-written `routing_triggers` / `instructions` and hand-picked `AgentSpecialistDocumentLink`s.

**Earned profiles** make that arrow real: an offline job that **auto-accretes** linked docs from real captured work and stamps `created_from="earned"`.

> **Why it matters (thesis D5):** seeded profiles are a demo prop and look like a shared-prompt library (the commodity). *Earned* profiles are the moat — *"we capture what your agents figure out, not what you write down."* This is the compounding input to the flywheel and the thing AGENTS.md structurally can't be.

## Current state (what exists, reuse it)

| Piece | Location | Role |
|---|---|---|
| `AgentSpecialist` + `created_from` (`"seeded"\|"earned"`) | `models.py` | the profile; the field this job flips |
| `AgentSpecialistDocumentLink` (uniq `specialist_id`+`document_id`, `weight`/`anchor_id`/`reason`/`is_pinned`) | `models.py` | the curated doc set — **idempotent by constraint** |
| `score_document(doc, DiscoveryRequest)` | `core/taskforce/scoring.py` | pure doc↔signals scorer — **reuse to rank docs against a specialist's triggers** |
| `list_v2_documents_for_actor` | `core/v2_documents.py` | org-visible candidate docs (self + organization) |
| `tokenize`, `band_for` | `core/taskforce/scoring.py` | shared token/band vocab |
| seeding helpers | `core/agents/seed.py` | the hand-built path this automates |

## The job — `compound_specialists()`

Offline, **out-of-loop** (cron/worker), org-scoped. Never called from `route_specialist` or any request path (sensor-not-processor).

```
for each active AgentSpecialist S in org O:
    signals = DiscoveryRequest(prompt=" ".join(S.routing_triggers + S.domain_tags))
    candidates = list_v2_documents_for_actor(... org O, non-demo ...)
    for doc D in candidates:
        s = score_document(D, signals).score
        if s >= MIN_LINK_SCORE:
            upsert AgentSpecialistDocumentLink(S, D, weight=s, reason="earned: matched <triggers>")
    prune links beyond MAX_LINKS_PER_SPECIALIST (lowest weight first; keep is_pinned)
    if S gained ≥1 earned link and S.created_from == "seeded":
        S.created_from = "earned"   # (or "hybrid" if it had seeded links — see open questions)
return report{specialists_seen, links_created, links_updated, promoted_to_earned}
```

**Optional second pass (trigger mining):** propose new `routing_triggers` from tokens (`tokenize`) recurring across a specialist's earned docs but absent from its current triggers — surfaced for review, **not auto-applied** (keep humans in the curation loop; flywheel-direction discipline).

## Guardrails (load-bearing — this is the curation valve)
- **Score threshold** `MIN_LINK_SCORE` (start 0.45, same as routing's `linked_doc_match` instinct) — junk in = wheel spins backward.
- **`MAX_LINKS_PER_SPECIALIST`** (start 25) — bound a profile's size; prune lowest-weight, never `is_pinned`.
- **`dry_run=True` default** — compute the plan, write nothing (mirror `observe.py` shadow-mode). Flip to write only when trusted.
- **Org-scoped + non-demo** — respect `visibility`; never cross orgs; keep seeded *demo* specialists untouched (`is_demo`).
- **Idempotent** — the unique constraint + upsert means re-runs converge, don't duplicate.
- **Provenance** — `reason` records *why* each link was earned; `created_from` records the profile's origin.

## Lifecycle / where it plugs in
- A worker entry (e.g. `app/scripts/compound_specialists.py`) and/or a scheduled task; **not** the request path.
- Entry-point stub already planted: **`app/core/agents/compounding.py`** (raises `NotImplementedError`, not imported anywhere).
- Seam noted in `core/agents/routing.py::route_specialist` docstring.

## Acceptance (for the build step that follows this design)
- Running `compound_specialists(dry_run=False)` over an org with real docs links the matching docs to the right specialist and flips `created_from` to `"earned"`; re-running is a no-op (idempotent).
- Unit tests follow `tests/core/test_taskforce_scoring.py` patterns (pure scoring) + an API/worker test for the write path.
- `route_specialist` behavior is unchanged — earned profiles flow through the *exact same* read path as seeded ones (this is why C6 is a clean add, not a rewrite).

## Open design questions
- **`created_from` values:** `seeded` / `earned` / a third `hybrid` for profiles with both? (Today the field is a free string ≤32.)
- **Specialist *discovery*** (create brand-new specialists from doc clusters) vs. only *enriching* existing ones — defer discovery; start with enrichment.
- **Weight decay** on links as docs age (reuse the 30d half-life from `scoring.py`)?
- **Trigger-mining auto-apply threshold** — likely never auto; always human-reviewed.
