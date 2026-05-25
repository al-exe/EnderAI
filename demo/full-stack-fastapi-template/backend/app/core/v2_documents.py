from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_
from sqlmodel import Session, col, select

from app.models import (
    User,
    V2Document,
    V2DocumentFavorite,
    V2DocumentFolder,
    V2DocumentFolderPublic,
    V2DocumentPublic,
    V2DocumentShare,
    V2DocumentSharePublic,
    V2DocumentUpdate,
    get_datetime_utc,
)


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


# Demo seed catalog. Each entry is cloned per-user the first time that user
# enables demo mode. Identifiers are generated per-clone; this catalog only
# provides the content payload.
DEMO_SEED: list[dict[str, Any]] = [
    {
        "title": "Latest Stale Network Bridge Issue",
        "description": (
            "Customer-impact investigation with a verified operator fix, a "
            "full timeline, and the operational record used to prevent the "
            "next recurrence."
        ),
        "created_at": _dt(2026, 5, 10),
        "updated_at": _dt(2026, 5, 12),
        "collaborators": ["Alex Lee", "Nia Patel", "Jordan Kim", "Sam Rivera"],
        "ai_generated_summary": (
            "XYZ Corp traffic hit stale bridge routes after a bridge-controller "
            "deploy. The recovery path was validated by refreshing the tenant "
            "bridge mapping and confirming post-refresh health checks. The "
            "incident also revealed a missing post-deploy verification step "
            "that has now been added to the bridge-controller rollout runbook."
        ),
        "human_summary": (
            "XYZ Corp users hit stale bridge routing after a deploy; the "
            "validated fix is Alex's bridge refresh script. The contributing "
            "factor was a bridge-controller rollout that did not refresh "
            "tenant route caches, and the prevention work is a post-deploy "
            "verification step the operator now runs before declaring the "
            "rollout healthy."
        ),
        "main_body": [
            {
                "segments": [
                    {"text": "After the bridge-controller deploy, "},
                    {
                        "text": "XYZ Corp users hit stale bridge routing",
                        "evidence_anchor_id": "affected-users",
                    },
                    {
                        "text": (
                            ". The incident showed up as intermittent requests "
                            "crossing old tenant bridge routes rather than the "
                            "refreshed bridge mapping. The pattern was strong "
                            "enough that the on-call could see it on the "
                            "tenant traffic dashboard within minutes of the "
                            "rollout completing."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "The first signal arrived from XYZ Corp customer "
                            "success at 14:02 UTC: a small but rising number "
                            "of API calls were returning 502s that traced "
                            "back to a bridge that had been deprecated in the "
                            "rollout. "
                        )
                    },
                    {
                        "text": ("The timeline matches a tenant-cache refresh gap"),
                        "evidence_anchor_id": "timeline",
                    },
                    {
                        "text": (
                            ". The bridge-controller rollout completed at "
                            "13:55 UTC; the first stale-route 502 landed "
                            "seven minutes later. There was no other rollout "
                            "or config change in the surrounding hour, which "
                            "made the bridge-controller the obvious starting "
                            "point for the investigation."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {"text": "The team recovered the tenant by running "},
                    {
                        "text": (
                            "Alex's bridge refresh script and validating "
                            "post-refresh probes"
                        ),
                        "evidence_anchor_id": "validated-fix",
                    },
                    {
                        "text": (
                            ". The useful operational record is the sequence "
                            "of logs, script execution, and health checks "
                            "captured in Details. The script is idempotent; "
                            "running it a second time produced no further "
                            "route changes and the probes stayed green."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "The contributing factor lived inside the "
                            "bridge-controller rollout itself. "
                        )
                    },
                    {
                        "text": (
                            "The rollout did not push a tenant-cache refresh "
                            "to the bridge sidecars"
                        ),
                        "evidence_anchor_id": "root-cause",
                    },
                    {
                        "text": (
                            ", so the sidecars continued serving the old "
                            "tenant→bridge mapping until the next scheduled "
                            "refresh. For tenants like XYZ that had their "
                            "bridge migrated as part of the rollout, the "
                            "old mapping pointed at a bridge that no longer "
                            "served their traffic."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "The recurring fix path is now part of the "
                            "operator runbook, but the original investigation "
                            "had to compare two route tables side-by-side to "
                            "be sure the refresh actually moved traffic. "
                        )
                    },
                    {
                        "text": ("We walked the route tables before and after"),
                        "evidence_anchor_id": "route-comparison",
                    },
                    {
                        "text": (
                            " using `bridge-routes --tenant xyz`, captured "
                            "both outputs into the incident channel, and "
                            "diffed them inline. The diff produced a single "
                            "row change pointing at the new bridge ID, which "
                            "matched the rollout's intended state."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {"text": ("Verification did not stop at the route table. ")},
                    {
                        "text": ("Post-refresh health probes ran for fifteen minutes"),
                        "evidence_anchor_id": "post-refresh-probes",
                    },
                    {
                        "text": (
                            " with the alert thresholds tightened, no new "
                            "stale-route 502s arrived, and the on-call "
                            "manually replayed three failing requests from "
                            "the original report. All three replays "
                            "succeeded, which is the bar we use to declare a "
                            "tenant recovered."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {"text": ("Customer communication ran on a parallel track. ")},
                    {
                        "text": ("The customer success thread closed at 14:48 UTC"),
                        "evidence_anchor_id": "customer-comms",
                    },
                    {
                        "text": (
                            " after the on-call posted the refresh "
                            "confirmation. The CS thread is the canonical "
                            "narrative for the customer-facing impact and is "
                            "referenced in the Details section so a future "
                            "agent can read the customer perspective without "
                            "leaving the document."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "Prevention work focused on stopping the same "
                            "rollout shape from leaving stale tenant caches "
                            "again. "
                        )
                    },
                    {
                        "text": (
                            "A post-deploy verification step now runs "
                            "before the rollout is marked healthy"
                        ),
                        "evidence_anchor_id": "prevention",
                    },
                    {
                        "text": (
                            ", and the script that drove the manual fix has "
                            "been moved into the rollout automation so the "
                            "controller refreshes tenant caches itself rather "
                            "than relying on the operator to notice."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "We had one prior incident that rhymed with this "
                            "one, although the surface symptom was different. "
                        )
                    },
                    {
                        "text": (
                            "The 2026-02 tenant-routing flap had the same root cause"
                        ),
                        "evidence_anchor_id": "prior-incident",
                    },
                    {
                        "text": (
                            " but the fix that landed back then was "
                            "tenant-specific. The Details section walks "
                            "through the difference and explains why the new "
                            "post-deploy check would have caught both."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "Finally, the post-incident review pulled out "
                            "two transferable lessons. "
                        )
                    },
                    {
                        "text": (
                            "Tenant cache state must be part of rollout verification"
                        ),
                        "evidence_anchor_id": "postmortem-takeaway",
                    },
                    {
                        "text": (
                            " for any controller that touches per-tenant "
                            "routing. The second is that idempotent operator "
                            "scripts should always live in the rollout "
                            "pipeline once they have been used to recover an "
                            "incident more than once."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "Future follow-ups, tracked in the runbook, "
                            "include extending the verification step to "
                            "other controllers that maintain tenant caches "
                            "and adding a per-tenant probe to the standard "
                            "rollout dashboard."
                        )
                    }
                ]
            },
        ],
        "details_file_name": "latest-stale-network-bridge-issue.details.md",
        "details_markdown_sections": [
            {
                "anchor_id": "document-context",
                "markdown": "\n".join(
                    [
                        "---",
                        "document_id: latest-stale-network-bridge-issue",
                        "title: Latest Stale Network Bridge Issue",
                        "created_at: 2026-05-10",
                        "updated_at: 2026-05-12",
                        "collaborators:",
                        "  - Alex Lee",
                        "  - Nia Patel",
                        "  - Jordan Kim",
                        "  - Sam Rivera",
                        "---",
                        "",
                        "# Latest Stale Network Bridge Issue",
                        "",
                        "## Purpose",
                        "",
                        "Capture the full investigation record for the stale "
                        "bridge routing incident so another agent can "
                        "understand the customer impact, reproduce the "
                        "checks, apply the known fix path, and ship the "
                        "prevention work without relying on chat history.",
                        "",
                        "## Executive Context",
                        "",
                        "A bridge-controller deploy left XYZ Corp traffic "
                        "reading stale tenant bridge routes. The immediate "
                        "remediation was to refresh the tenant bridge "
                        "mapping and verify the post-refresh probes. The "
                        "deeper fix was to move that refresh into the "
                        "rollout itself, plus add a verification gate.",
                        "",
                        "## How To Read This Document",
                        "",
                        "Summary tells the story for a human reader. Details "
                        "below is the working log: every anchored claim in "
                        "Summary maps to a section here, and the section "
                        "carries the commands, logs, and reasoning that "
                        "justify the claim.",
                    ]
                ),
            },
            {
                "anchor_id": "affected-users",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: affected-users -->",
                        "## Affected Users And Symptoms",
                        "",
                        "XYZ Corp tenants reported intermittent requests "
                        "crossing stale network bridge routes immediately "
                        "after the bridge-controller deploy.",
                        "",
                        "Observed pattern:",
                        "",
                        "- tenant: `xyz`",
                        "- symptom: requests occasionally used old bridge mappings",
                        "- timing: began immediately after the "
                        "bridge-controller rollout",
                        "- user impact: intermittent routing failures for "
                        "XYZ Corp users",
                        "- blast radius: contained to tenants migrated in "
                        "this rollout (XYZ plus two smaller tenants we "
                        "verified by hand)",
                        "",
                        "Primary checks:",
                        "",
                        "```bash",
                        "kubectl logs deploy/bridge-controller",
                        "kubectl get bridge-routes --tenant xyz",
                        "kubectl get bridge-routes --tenant abc",
                        "kubectl get bridge-routes --tenant def",
                        "```",
                        "",
                        "The route table inspection confirmed that the "
                        "tenant mapping had not refreshed to the expected "
                        "post-deploy bridge target. The two smaller tenants "
                        "showed the same shape; the on-call refreshed them "
                        "preemptively before customer-visible symptoms "
                        "appeared.",
                    ]
                ),
            },
            {
                "anchor_id": "timeline",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: timeline -->",
                        "## Timeline",
                        "",
                        "All times UTC.",
                        "",
                        "- 13:48 — bridge-controller rollout started",
                        "- 13:55 — rollout reported complete by the "
                        "controller deploy job",
                        "- 14:02 — first XYZ Corp customer success ping (rising 502s)",
                        "- 14:05 — on-call paged; on-call enters incident "
                        "channel and confirms the alert pattern",
                        "- 14:09 — `bridge-routes --tenant xyz` shows stale "
                        "mapping; hypothesis confirmed",
                        "- 14:14 — `bridge-refresh.sh --tenant xyz` "
                        "executed; route table updated within five seconds",
                        "- 14:16 — replayed customer requests succeed; "
                        "alert volume drops",
                        "- 14:25 — preemptive refreshes for two smaller "
                        "tenants completed",
                        "- 14:32 — fifteen-minute clean window declared",
                        "- 14:48 — customer success thread closed with "
                        "confirmation message",
                        "",
                        "The seven-minute gap between rollout completion "
                        "and first customer impact is the tenant cache "
                        "TTL plus a handful of cached client connections; "
                        "this is consistent with the [[prior-incident]] "
                        "behaviour.",
                    ]
                ),
            },
            {
                "anchor_id": "validated-fix",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: validated-fix -->",
                        "## Validated Fix",
                        "",
                        "The fix path was to run Alex's tenant bridge "
                        "refresh script, then verify bridge health with "
                        "post-refresh probes.",
                        "",
                        "Command used:",
                        "",
                        "```bash",
                        "./infra/network/bridge-refresh.sh --tenant xyz",
                        "```",
                        "",
                        "Files referenced:",
                        "",
                        "- `infra/network/bridge-refresh.sh`",
                        "- `ops/runbooks/network-bridge.md`",
                        "- `infra/network/bridge-controller/rollout.yaml`",
                        "",
                        "Verification:",
                        "",
                        "- route table changed to the expected bridge target",
                        "- post-refresh health probes passed for the full "
                        "fifteen-minute window",
                        "- no additional stale-route reports arrived for "
                        "XYZ Corp after the refresh",
                        "- three replayed customer requests succeeded",
                        "- the script is safe to re-run; a second "
                        "execution produced no further state changes",
                    ]
                ),
            },
            {
                "anchor_id": "root-cause",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: root-cause -->",
                        "## Root Cause",
                        "",
                        "The bridge-controller rollout updated the "
                        "controller's own view of tenant→bridge mappings "
                        "but did not propagate that change to the bridge "
                        "sidecars. Sidecars hold a per-tenant cache of "
                        "their target bridge so that lookups stay off "
                        "the controller's hot path.",
                        "",
                        "When the rollout completed, the cache was still "
                        "valid by TTL, so the sidecars continued to serve "
                        "the previous mapping. Tenants like XYZ whose "
                        "bridge had been migrated as part of the rollout "
                        "kept routing to a bridge that no longer "
                        "served their traffic, which produced the 502s.",
                        "",
                        "The fix is twofold: refresh tenant caches as "
                        "part of the rollout (now done by the controller "
                        "itself), and verify that the refresh actually "
                        "moved the per-tenant route before the rollout "
                        "is marked healthy.",
                    ]
                ),
            },
            {
                "anchor_id": "route-comparison",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: route-comparison -->",
                        "## Route Table Comparison",
                        "",
                        "Before refresh:",
                        "",
                        "```text",
                        "tenant   bridge_id            updated_at",
                        "xyz      bridge-7a2f          2026-05-10T13:11Z",
                        "```",
                        "",
                        "After refresh:",
                        "",
                        "```text",
                        "tenant   bridge_id            updated_at",
                        "xyz      bridge-9c81          2026-05-10T14:14Z",
                        "```",
                        "",
                        "The diff is a single column change — the "
                        "`bridge_id` moved from the pre-rollout target to "
                        "the post-rollout target — which is exactly the "
                        "shape the rollout was supposed to produce. The "
                        "`updated_at` column shifts to the refresh time, "
                        "which is how the new verification step "
                        "asserts the refresh actually happened.",
                    ]
                ),
            },
            {
                "anchor_id": "post-refresh-probes",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: post-refresh-probes -->",
                        "## Post-Refresh Probes",
                        "",
                        "Probe command:",
                        "",
                        "```bash",
                        "./ops/probes/bridge-health --tenant xyz \\",
                        "  --duration 15m --threshold tight",
                        "```",
                        "",
                        "Output:",
                        "",
                        "```text",
                        "✓ probe-1 ok  (latency p50=22ms p99=80ms)",
                        "✓ probe-2 ok  (latency p50=21ms p99=74ms)",
                        "✓ probe-3 ok  (latency p50=23ms p99=88ms)",
                        "✓ probe-4 ok  (latency p50=22ms p99=79ms)",
                        "...",
                        "✓ probe-15 ok (latency p50=22ms p99=82ms)",
                        "```",
                        "",
                        "No probe failed, no replayed customer request "
                        "failed, and the alert thresholds stayed quiet "
                        "for the full window. This is the bar the "
                        "incident rotation uses to declare a tenant "
                        "recovered.",
                    ]
                ),
            },
            {
                "anchor_id": "customer-comms",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: customer-comms -->",
                        "## Customer Communication",
                        "",
                        "The customer success thread for this incident is "
                        "the canonical narrative for what XYZ Corp saw, "
                        "what we said, and when we said it. It is "
                        "linked here so a future agent has the "
                        "customer perspective without leaving the "
                        "document.",
                        "",
                        "Key beats from the thread:",
                        "",
                        "- 14:02 — XYZ CS reports intermittent 502s",
                        "- 14:09 — we acknowledge, share rough scope, "
                        "and commit to an ETA inside 30 minutes",
                        "- 14:14 — we confirm the fix is rolling",
                        "- 14:25 — we confirm broader tenant scan and "
                        "preemptive refreshes for two smaller tenants",
                        "- 14:48 — we close the thread with the post-"
                        "refresh probe results",
                        "",
                        "The CS thread also captures XYZ's customer "
                        "preference for a written follow-up; the "
                        "post-incident note we sent the next day is "
                        "linked from the runbook.",
                    ]
                ),
            },
            {
                "anchor_id": "prevention",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: prevention -->",
                        "## Prevention Work",
                        "",
                        "Two concrete changes landed before the rollout "
                        "automation was re-enabled.",
                        "",
                        "1. The bridge-controller now invokes the "
                        "tenant-cache refresh path for every tenant "
                        "whose bridge was migrated in the rollout. This "
                        "removes the operator-in-the-loop step.",
                        "2. The rollout job runs a verification gate "
                        "that re-queries the per-tenant route table "
                        "after the refresh and asserts that "
                        "`updated_at` advanced past the rollout start "
                        "time. If it has not, the rollout is paused "
                        "and the on-call is paged.",
                        "",
                        "Files changed:",
                        "",
                        "- `infra/network/bridge-controller/rollout.yaml`",
                        "- `infra/network/bridge-controller/verify.py`",
                        "- `ops/runbooks/network-bridge.md`",
                    ]
                ),
            },
            {
                "anchor_id": "prior-incident",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: prior-incident -->",
                        "## Prior Incident: 2026-02 Tenant Routing Flap",
                        "",
                        "We had a related incident in February 2026 with "
                        "a different surface symptom but the same "
                        "underlying gap: a controller rollout updated "
                        "its internal view of tenant routing without "
                        "refreshing downstream caches.",
                        "",
                        "Differences:",
                        "",
                        "- the February incident affected per-region "
                        "edge proxies, not bridge sidecars",
                        "- the symptom was a soft latency regression rather than 502s",
                        "- the fix at the time was tenant-specific "
                        "(`edge-refresh.sh --tenant xyz`)",
                        "",
                        "Lesson carried forward: any controller that "
                        "owns per-tenant caches must include a "
                        "cache-refresh and verification step in its "
                        "rollout. The new bridge-controller behaviour "
                        "is the second time we have applied this "
                        "pattern; the edge-proxy controller has the "
                        "same shape since March.",
                    ]
                ),
            },
            {
                "anchor_id": "postmortem-takeaway",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: postmortem-takeaway -->",
                        "## Post-Incident Review Takeaways",
                        "",
                        "Two transferable lessons from the review:",
                        "",
                        "1. **Tenant cache state is part of rollout "
                        "verification.** Any controller that maintains "
                        "per-tenant caches has to refresh and verify "
                        "those caches before the rollout is healthy. "
                        "We have now applied this to two controllers; "
                        "the third (the workflow router) is in scope "
                        "for next quarter.",
                        "2. **Idempotent operator scripts should "
                        "migrate into the rollout.** The bridge-refresh "
                        "script existed and worked, but it required a "
                        "human to notice the problem and run it. Once "
                        "we have run a script twice for the same "
                        "rollout shape, the next step is to embed it "
                        "in the rollout automation.",
                        "",
                        "Both points are now in the rollout review "
                        "checklist so they are applied to future "
                        "controllers from the start.",
                    ]
                ),
            },
            {
                "anchor_id": "commands",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: commands -->",
                        "## Commands Run",
                        "",
                        "```bash",
                        "kubectl logs deploy/bridge-controller",
                        "kubectl get bridge-routes --tenant xyz",
                        "kubectl get bridge-routes --tenant abc",
                        "kubectl get bridge-routes --tenant def",
                        "./infra/network/bridge-refresh.sh --tenant xyz",
                        "./infra/network/bridge-refresh.sh --tenant abc",
                        "./infra/network/bridge-refresh.sh --tenant def",
                        "./ops/probes/bridge-health --tenant xyz "
                        "--duration 15m --threshold tight",
                        "```",
                        "",
                        "## Open Follow-Up",
                        "",
                        "- Extend rollout cache-verification to the "
                        "workflow router controller",
                        "- Add a per-tenant bridge probe to the "
                        "standard rollout dashboard",
                        "- Schedule a quarterly review of which "
                        "controllers own per-tenant caches",
                        "- Migrate the remaining tenant-specific "
                        "refresh scripts under `ops/runbooks/` into "
                        "their owning rollouts",
                    ]
                ),
            },
        ],
    },
    {
        "title": "V2 Document Evidence Contract",
        "description": (
            "Design note for Summary claims backed by source anchors in "
            "Details, with the UX research, data model rationale, and "
            "rollout plan that justifies the shape."
        ),
        "created_at": _dt(2026, 5, 13),
        "updated_at": _dt(2026, 5, 14),
        "collaborators": ["Alex Lee", "Jordan Kim", "Riley Chen"],
        "ai_generated_summary": (
            "The V2 document model should keep executive summaries short "
            "while making each claim traceable to a Details section or "
            "another source document. The contract is enforced both in the "
            "UX (clickable anchors) and in the data model "
            "(`evidence_anchor_id` on segments, `anchor_id` on detail "
            "sections), and the rollout staged it behind a per-user flag."
        ),
        "human_summary": (
            "Human summaries should stay short, but each claim needs a "
            "direct path to detailed evidence. The contract is enforced "
            "by the data model and rendered by the UI; future extensions "
            "include cross-document anchors and AI-assisted backfill."
        ),
        "main_body": [
            {
                "segments": [
                    {
                        "text": (
                            "The Summary view should tell a short story "
                            "first: what happened, why it matters, and what "
                            "changed. "
                        )
                    },
                    {
                        "text": "It should stay succinct and executive-oriented",
                        "evidence_anchor_id": "summary-shape",
                    },
                    {
                        "text": (
                            " so a reader can understand the outcome "
                            "without reading the full working log."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {"text": "The detail should still be verifiable. "},
                    {
                        "text": (
                            "Each important Summary claim needs a direct "
                            "path to supporting evidence"
                        ),
                        "evidence_anchor_id": "claim-evidence",
                    },
                    {
                        "text": (
                            ", whether that evidence lives in Details or "
                            "another linked document. The default expectation "
                            "is that a claim worth highlighting is a claim "
                            "worth anchoring."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "The shape came out of user research with the "
                            "first cohort of Taskforce users. "
                        )
                    },
                    {
                        "text": (
                            "Operators wanted a one-screen narrative they "
                            "could share, plus a deep log they could trust"
                        ),
                        "evidence_anchor_id": "ux-research",
                    },
                    {
                        "text": (
                            ". The two surfaces had to live in the same "
                            "document so that the narrative could not drift "
                            "from the evidence over time. Splitting them "
                            "across two artifacts had been tried previously "
                            "and produced exactly the drift the contract is "
                            "trying to prevent."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {"text": ("The data model encodes the contract directly. ")},
                    {
                        "text": (
                            "Summary segments carry an optional `evidence_anchor_id`"
                        ),
                        "evidence_anchor_id": "data-model",
                    },
                    {
                        "text": (
                            " and Details sections carry an `anchor_id`; "
                            "the UI renders matching anchors as clickable "
                            "evidence and a non-matching anchor is flagged "
                            "in the editor so a writer can fix the link "
                            "before publishing."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {"text": ("Rendering is intentionally minimal. ")},
                    {
                        "text": (
                            "Anchored Summary spans are inline buttons that "
                            "switch to Split view and highlight the matching "
                            "Details section"
                        ),
                        "evidence_anchor_id": "anchor-rendering",
                    },
                    {
                        "text": (
                            ". There is no separate sidebar, no footnote "
                            "tray, and no popover; the goal is for the "
                            "evidence to feel like a continuation of the "
                            "Summary reading flow rather than an interruption."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "Authoring is the part of the contract that "
                            "still needs the most work. "
                        )
                    },
                    {
                        "text": (
                            "The editor must let a writer select text and "
                            "convert it into an anchored claim in one "
                            "interaction"
                        ),
                        "evidence_anchor_id": "authoring",
                    },
                    {
                        "text": (
                            ". The first implementation of the Link evidence "
                            "flow does exactly this: highlight in Summary, "
                            "highlight the matching markdown in Details, "
                            "confirm. The anchor ID is generated for the "
                            "writer; they only have to agree on what is "
                            "evidence for what."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {"text": ("Cross-document evidence is the next step. ")},
                    {
                        "text": (
                            "An anchor will be allowed to point at another "
                            "document's section"
                        ),
                        "evidence_anchor_id": "cross-document",
                    },
                    {
                        "text": (
                            " so that operator runbooks and post-incident "
                            "writeups can reuse the same evidence without "
                            "duplicating it. The rendering for cross-"
                            "document anchors will still keep the same "
                            "inline-button affordance; the only difference "
                            "is the target."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "The rollout is gated on the per-user `v2` "
                            "flag so it can be enabled on a per-team basis. "
                        )
                    },
                    {
                        "text": (
                            "Existing case-and-topic data is preserved and "
                            "remains available for users who have not yet "
                            "switched"
                        ),
                        "evidence_anchor_id": "rollout-plan",
                    },
                    {
                        "text": (
                            ". The plan is to enable V2 for the "
                            "internal team first, gather a week of "
                            "authoring feedback, then expand."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {"text": ("AI assistance is the longest-horizon extension. ")},
                    {
                        "text": (
                            "A backfill pass will scan existing Details "
                            "sections and suggest evidence anchors for "
                            "Summary claims that lack them"
                        ),
                        "evidence_anchor_id": "ai-assist",
                    },
                    {
                        "text": (
                            ". This is explicitly opt-in per document and "
                            "the writer always approves the suggestion "
                            "before it is applied — the anchor contract "
                            "is a human commitment, not an automated one."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "Risks and tradeoffs are summarized in the "
                            "Details section, but the headline risk is the "
                            "authoring friction the anchor flow adds. We "
                            "are accepting that friction in exchange for "
                            "the trust benefit, and we are tracking time-"
                            "to-publish in the first cohort to make sure "
                            "the tradeoff stays acceptable."
                        )
                    }
                ]
            },
        ],
        "details_file_name": "v2-document-evidence-contract.details.md",
        "details_markdown_sections": [
            {
                "anchor_id": "document-context",
                "markdown": "\n".join(
                    [
                        "---",
                        "document_id: v2-document-evidence-contract",
                        "title: V2 Document Evidence Contract",
                        "created_at: 2026-05-13",
                        "updated_at: 2026-05-14",
                        "collaborators:",
                        "  - Alex Lee",
                        "  - Jordan Kim",
                        "  - Riley Chen",
                        "---",
                        "",
                        "# V2 Document Evidence Contract",
                        "",
                        "## Purpose",
                        "",
                        "Define how Taskforce V2 documents preserve a "
                        "concise human Summary while retaining enough "
                        "Details for an AI agent to reconstruct the work. "
                        "The contract has to hold both at write time (the "
                        "editor enforces anchor links) and at read time "
                        "(the UI surfaces anchored claims and their "
                        "evidence in one view).",
                        "",
                        "## Scope",
                        "",
                        "This document covers the data model, the UX, the "
                        "authoring flow, and the rollout plan for V2 "
                        "documents. It does not cover the legacy "
                        "case-and-topic data model, which continues to "
                        "exist alongside V2 for users who have not "
                        "switched.",
                    ]
                ),
            },
            {
                "anchor_id": "summary-shape",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: summary-shape -->",
                        "## Summary Shape",
                        "",
                        "The Summary view is intentionally succinct and "
                        "executive-oriented. It should capture intent, "
                        "outcome, and high-level points without exposing "
                        "the full capture log by default.",
                        "",
                        "The Summary should answer:",
                        "",
                        "- what happened",
                        "- why it mattered",
                        "- what changed",
                        "- what the next reader should do",
                        "",
                        "Length guidance for the human summary is two to "
                        "five sentences. The main body adds the narrative "
                        "context but should still read as a story, not a "
                        "log. When the narrative is longer than ten "
                        "paragraphs, that is a signal to either split the "
                        "document or move material into Details.",
                    ]
                ),
            },
            {
                "anchor_id": "claim-evidence",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: claim-evidence -->",
                        "## Claim Evidence Links",
                        "",
                        "Every important Summary claim must point to an "
                        "evidence anchor in Details or another document.",
                        "",
                        "Implementation notes:",
                        "",
                        "- inline highlighted Summary text stores an "
                        "`evidence_anchor_id`",
                        "- Details markdown uses `<!-- evidence-anchor: "
                        "anchor-id -->` comments",
                        "- clicking a Summary claim switches to Details "
                        "and highlights the matching markdown section",
                        "- the Details content remains valid markdown "
                        "when concatenated",
                        "",
                        "When a Summary claim has no anchor, the editor "
                        "shows a non-blocking warning. The warning is "
                        "non-blocking because a claim that is itself "
                        'executive context ("this matters because…") '
                        "may legitimately have no separate evidence; the "
                        "writer is asked to confirm that case explicitly.",
                    ]
                ),
            },
            {
                "anchor_id": "ux-research",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: ux-research -->",
                        "## UX Research Findings",
                        "",
                        "Five operators were interviewed in the first "
                        "cohort. The shared signal was that the existing "
                        "case-and-topic flow produced two artifacts that "
                        "drifted: the customer-facing summary and the "
                        "internal working log. Operators trusted the "
                        "working log and shared the summary; over time the "
                        "summary stopped reflecting the log.",
                        "",
                        "Operators were asked to describe an ideal "
                        "shape, and the responses converged on:",
                        "",
                        "- one document per piece of work",
                        "- a short narrative on top",
                        "- a deep log below",
                        "- a visible connection between specific claims "
                        "in the narrative and specific sections of the log",
                        "",
                        "That last requirement is the evidence anchor "
                        "contract. The other three drove the Summary / "
                        "Details / Split view shape.",
                    ]
                ),
            },
            {
                "anchor_id": "data-model",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: data-model -->",
                        "## Data Model",
                        "",
                        "A V2 document has the following structure:",
                        "",
                        "```python",
                        "class V2Document:",
                        "    id: UUID",
                        "    owner_id: UUID",
                        "    title: str",
                        "    description: str",
                        "    human_summary: str",
                        "    ai_generated_summary: str",
                        "    collaborators: list[str]",
                        "    main_body: list[V2DocumentParagraph]",
                        "    details_file_name: str",
                        "    details_markdown_sections: list[V2DocumentDetailsSection]",
                        "    is_demo: bool",
                        "    created_at: datetime | None",
                        "    updated_at: datetime | None",
                        "",
                        "class V2DocumentParagraph:",
                        "    segments: list[V2DocumentSegment]",
                        "",
                        "class V2DocumentSegment:",
                        "    text: str",
                        "    evidence_anchor_id: str | None",
                        "",
                        "class V2DocumentDetailsSection:",
                        "    anchor_id: str",
                        "    markdown: str",
                        "```",
                        "",
                        "The contract is enforced at three layers: the "
                        "model (anchor IDs are first-class fields), the "
                        "editor (linking is a single interaction), and "
                        "the renderer (anchors round-trip between "
                        "Summary clicks and Details highlights).",
                    ]
                ),
            },
            {
                "anchor_id": "anchor-rendering",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: anchor-rendering -->",
                        "## Anchor Rendering",
                        "",
                        "Anchored Summary spans render as inline buttons "
                        "with a subtle highlight. Clicking the button:",
                        "",
                        "1. switches the view to Split",
                        "2. scrolls the Details pane to the matching section",
                        "3. visually highlights the section so the reader "
                        "can see what they are being pointed at",
                        "",
                        "The close affordance on Split returns to Summary "
                        "and clears the active anchor highlight. The "
                        "design choice that took longest to settle was "
                        "whether anchor activation should ever leave "
                        "the document; the answer is no. Evidence lives "
                        "inside the document by default, and cross-"
                        "document anchors are explicit (see the [[cross-"
                        "document]] section below).",
                    ]
                ),
            },
            {
                "anchor_id": "authoring",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: authoring -->",
                        "## Authoring Flow",
                        "",
                        "The authoring flow has two operations: edit "
                        "text, and link evidence.",
                        "",
                        "Edit text:",
                        "",
                        "- Click Edit on a document",
                        "- Title, description, summaries, and "
                        "collaborators are simple form fields",
                        "- Main body segments are editable in place; "
                        "anchored segments remain anchored",
                        "- Details sections are editable as markdown textareas",
                        "- Save submits a single PATCH; Cancel reverts",
                        "",
                        "Link evidence (split view only):",
                        "",
                        "- Click Link evidence to enter selection mode",
                        "- Select a span of text in Summary (within a "
                        "non-anchored segment)",
                        "- Select a span of text in Details (within a single section)",
                        "- Click Confirm anchor",
                        "- The summary segment is split into "
                        "`[before, anchored, after]`; the details "
                        "section is split the same way; both halves "
                        "share a fresh anchor ID",
                        "- The new anchor is immediately clickable",
                    ]
                ),
            },
            {
                "anchor_id": "cross-document",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: cross-document -->",
                        "## Cross-Document Anchors (planned)",
                        "",
                        "Cross-document anchors are not in the initial "
                        "release. The plan is to allow a Summary segment "
                        "to point at another document's section using a "
                        "qualified anchor ID (`<document_id>#<anchor_id>`). "
                        "Rendering remains the same inline-button "
                        "affordance; clicking opens the target document "
                        "in Split view scrolled to the relevant section.",
                        "",
                        "Open questions:",
                        "",
                        "- how to handle deletion of the target section",
                        "- whether the source document should pin the "
                        "target document version",
                        "- how cross-document anchors interact with "
                        "search and AI assist",
                        "",
                        "These will be resolved in a follow-up design "
                        "note once we have authoring feedback from the "
                        "first cohort.",
                    ]
                ),
            },
            {
                "anchor_id": "rollout-plan",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: rollout-plan -->",
                        "## Rollout Plan",
                        "",
                        "V2 is gated on the per-user `v2` flag. Phases:",
                        "",
                        "1. Internal dogfood — Taskforce team only (current state)",
                        "2. Selected design partners — a small set of "
                        "external operators with a direct feedback "
                        "channel",
                        "3. General availability behind opt-in",
                        "4. General availability with opt-out",
                        "",
                        "Phase gates require:",
                        "",
                        "- authoring time-to-publish has not regressed "
                        "more than 25% relative to V1",
                        "- no severity-1 incidents in the editor or "
                        "renderer for two consecutive weeks",
                        "- AI-assist suggestions have above-baseline "
                        "acceptance from the internal cohort",
                    ]
                ),
            },
            {
                "anchor_id": "ai-assist",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: ai-assist -->",
                        "## AI Assist",
                        "",
                        "AI assist is opt-in per document. The first "
                        "capability is a backfill pass that suggests "
                        "evidence anchors for Summary claims that "
                        "currently lack them.",
                        "",
                        "Suggestion flow:",
                        "",
                        "- writer opens AI assist panel",
                        "- system reads main body and details",
                        "- for each non-anchored Summary span longer "
                        "than a configurable threshold, the system "
                        "proposes the most likely details section",
                        "- writer accepts, rejects, or edits the suggestion",
                        "- accepted suggestions become real anchors and "
                        "the document is PATCHed",
                        "",
                        "The contract is a human commitment, so the "
                        "system never applies a suggestion without "
                        "explicit acceptance.",
                    ]
                ),
            },
            {
                "anchor_id": "commands",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: commands -->",
                        "## Commands Run",
                        "",
                        "```bash",
                        "npm run build",
                        "uv run pytest backend/app/tests/api/test_v2_documents_api.py",
                        "npx tsc -p tsconfig.build.json --noEmit",
                        "npx biome check --write --unsafe ./",
                        "```",
                        "",
                        "## Open Follow-Up",
                        "",
                        "- Resolve the cross-document anchor design questions",
                        "- Define the AI-assist acceptance metric",
                        "- Ship the V2 editor multi-cursor support "
                        "(currently single-selection only)",
                        "- Add anchor-coverage metrics to the document "
                        "list so writers can see uncited claims at a "
                        "glance",
                    ]
                ),
            },
        ],
    },
    {
        "title": "Hosted MCP Credential Setup Refresh",
        "description": (
            "Setup guidance for connecting an AI client with file-backed "
            "token persistence, plus the V2 instruction set for Taskforce "
            "v2 users and the operational guardrails the team learned "
            "the hard way."
        ),
        "created_at": _dt(2026, 5, 15),
        "updated_at": _dt(2026, 5, 17),
        "collaborators": ["Alex Lee", "Sam Rivera"],
        "ai_generated_summary": (
            "The hosted MCP setup now emphasizes file-backed token "
            "persistence, fresh-terminal reconnect steps, and a "
            "V2-specific document instruction set for V2-enabled users. "
            "The refresh also captures the operational guardrails the "
            "team learned the hard way: rotate after a leaked token, "
            "verify the active token with `mcp whoami`, and prefer "
            "single-tenant tokens for shared machines."
        ),
        "human_summary": (
            "Fresh terminals prevent stale MCP credentials from "
            "persisting after token creation or rotation. The refresh "
            "explains the supporting `mcp whoami` check, the rotation "
            "playbook for leaks, and the V2 instruction set that "
            "tells agents to author Taskforce documents instead of "
            "legacy cases."
        ),
        "main_body": [
            {
                "segments": [
                    {
                        "text": (
                            "The credential setup flow was refreshed "
                            "because token rotation can leave old "
                            "environment values in already-open shells. "
                        )
                    },
                    {
                        "text": (
                            "Starting from a fresh terminal prevents "
                            "stale MCP credentials from persisting"
                        ),
                        "evidence_anchor_id": "fresh-terminal",
                    },
                    {"text": " after a token is created or rotated."},
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "The setup uses a file-backed token store "
                            "so that the value is durable across shells. "
                        )
                    },
                    {
                        "text": ("`~/.enderai_mcp_token` is the canonical location"),
                        "evidence_anchor_id": "token-store",
                    },
                    {
                        "text": (
                            ", and the setup script writes the file with "
                            "0600 permissions so other users on the same "
                            "machine cannot read it. The script also "
                            "exports `ENDERAI_MCP_TOKEN` for the current "
                            "shell, which is why a *new* shell is what "
                            "you need after rotation."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "Before declaring setup complete, run a "
                            "verification command. "
                        )
                    },
                    {
                        "text": ("`mcp whoami` returns the token identity and tenant"),
                        "evidence_anchor_id": "verify",
                    },
                    {
                        "text": (
                            " and is the canonical proof that the shell "
                            "and client agree on which credential is "
                            "active. If the identity does not match the "
                            "expected user, you have a stale shell — "
                            "open a new terminal and re-run."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {"text": ("Rotation has its own playbook. ")},
                    {
                        "text": ("Rotate immediately on suspected leak"),
                        "evidence_anchor_id": "rotation",
                    },
                    {
                        "text": (
                            ". The rotation command invalidates the old "
                            "token, writes the new one to "
                            "`~/.enderai_mcp_token`, and prints the "
                            "fresh-terminal reminder. Tokens have a "
                            "default 30-day TTL so even tokens that "
                            "are forgotten will eventually rotate "
                            "themselves out."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "On shared machines or CI runners, the "
                            "guidance is stricter. "
                        )
                    },
                    {
                        "text": ("Use single-tenant tokens with scoped permissions"),
                        "evidence_anchor_id": "shared-machines",
                    },
                    {
                        "text": (
                            " so that a leak on a shared machine cannot "
                            "compromise other tenants. The CI integration "
                            "documentation walks through the GitHub "
                            "Actions and GitLab CI setups; both inject "
                            "the token as a masked secret rather than "
                            "writing it to disk."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "For V2-enabled users, the setup "
                            "instructions now push agents toward "
                            "Taskforce documents instead of legacy "
                            "cases. "
                        )
                    },
                    {
                        "text": (
                            "Those users should receive document "
                            "creation, update, and finalize instructions"
                        ),
                        "evidence_anchor_id": "v2-instructions",
                    },
                    {
                        "text": (
                            " so meaningful work is captured as a "
                            "Summary backed by Details. The agent never "
                            "edits the legacy case-and-topic model on a "
                            "V2 account."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "Agents on V2 accounts should also follow "
                            "the document lifecycle rules. "
                        )
                    },
                    {
                        "text": (
                            "Create a document at the start of "
                            "meaningful work, keep it up to date, and "
                            "finalize it at the end"
                        ),
                        "evidence_anchor_id": "lifecycle",
                    },
                    {
                        "text": (
                            ". This is what makes the working log useful "
                            "to the next agent (or operator) — the "
                            "document carries enough context to "
                            "reproduce the outcome without re-running "
                            "the chat."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {"text": ("Connection issues fall into a handful of categories. ")},
                    {
                        "text": (
                            "The four common failure modes are stale "
                            "shells, expired tokens, network egress, "
                            "and clock skew"
                        ),
                        "evidence_anchor_id": "troubleshooting",
                    },
                    {
                        "text": (
                            ". The Details section has a one-line "
                            "diagnostic for each, and the canonical "
                            "first step is always to open a new "
                            "terminal — that catches both stale shell "
                            "and several flavours of cached client "
                            "state."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "Finally, the refresh added a short note on "
                            "what *not* to do. "
                        )
                    },
                    {
                        "text": (
                            "Do not commit `~/.enderai_mcp_token`, do "
                            "not paste tokens into chat, and do not "
                            "share a single token across multiple "
                            "operators"
                        ),
                        "evidence_anchor_id": "anti-patterns",
                    },
                    {
                        "text": (
                            ". These rules are not new, but they were "
                            "scattered across three pages before the "
                            "refresh; they live in one place now."
                        )
                    },
                ]
            },
        ],
        "details_file_name": "hosted-mcp-credential-setup-refresh.details.md",
        "details_markdown_sections": [
            {
                "anchor_id": "document-context",
                "markdown": "\n".join(
                    [
                        "---",
                        "document_id: hosted-mcp-credential-setup-refresh",
                        "title: Hosted MCP Credential Setup Refresh",
                        "created_at: 2026-05-15",
                        "updated_at: 2026-05-17",
                        "collaborators:",
                        "  - Alex Lee",
                        "  - Sam Rivera",
                        "---",
                        "",
                        "# Hosted MCP Credential Setup Refresh",
                        "",
                        "## Purpose",
                        "",
                        "Capture the setup behavior, the rotation "
                        "playbook, and the V2 instruction updates for "
                        "hosted MCP credentials so future agents know "
                        "how credentials should be created, rotated, "
                        "and documented.",
                        "",
                        "## Audience",
                        "",
                        "Operators connecting an AI client to hosted "
                        "MCP for the first time, operators rotating an "
                        "existing token, and agents reading the "
                        "instruction set on a V2-enabled account.",
                    ]
                ),
            },
            {
                "anchor_id": "fresh-terminal",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: fresh-terminal -->",
                        "## Fresh Terminal Requirement",
                        "",
                        "The setup flow tells users to start from a "
                        "fresh terminal after creating or rotating an "
                        "MCP credential so the shell reloads "
                        "`ENDERAI_MCP_TOKEN` from "
                        "`~/.enderai_mcp_token`.",
                        "",
                        "Reason:",
                        "",
                        "- existing shells may keep the previous token in memory",
                        "- file-backed token persistence only helps "
                        "after the shell reloads the environment",
                        "- reconnecting the AI client from a fresh "
                        "terminal avoids stale credential handshakes",
                        "- some clients also cache the credential "
                        "in-process; restarting the client picks up "
                        "the new token without ambiguity",
                    ]
                ),
            },
            {
                "anchor_id": "token-store",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: token-store -->",
                        "## File-Backed Token Store",
                        "",
                        "Canonical location: `~/.enderai_mcp_token`.",
                        "",
                        "Properties:",
                        "",
                        "- written with mode 0600",
                        "- contains exactly one token, no surrounding whitespace",
                        "- read by the MCP client at startup and "
                        "exported as `ENDERAI_MCP_TOKEN` for the "
                        "current shell by the setup script",
                        "",
                        "Setup script extract:",
                        "",
                        "```bash",
                        "umask 077",
                        'printf \'%s\' "$TOKEN" > "$HOME/.enderai_mcp_token"',
                        'export ENDERAI_MCP_TOKEN="$TOKEN"',
                        "echo 'Open a fresh terminal to use the new token.'",
                        "```",
                        "",
                        "The fresh-terminal reminder is printed every "
                        "time so users are never expected to remember "
                        "the requirement.",
                    ]
                ),
            },
            {
                "anchor_id": "verify",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: verify -->",
                        "## Verification With `mcp whoami`",
                        "",
                        "Run `mcp whoami` after setup. The expected "
                        "output is the user's email and tenant:",
                        "",
                        "```text",
                        "$ mcp whoami",
                        "email:   alex@example.com",
                        "tenant:  enderai-internal",
                        "token:   short-id mcp_***xyz",
                        "expires: 2026-06-14T00:00:00Z",
                        "```",
                        "",
                        "Failure modes:",
                        "",
                        "- empty output → the shell has no token; "
                        "source the file or open a new terminal",
                        "- wrong email → a previous token is still in "
                        "the environment; open a new terminal",
                        "- expired output → run the rotation flow",
                    ]
                ),
            },
            {
                "anchor_id": "rotation",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: rotation -->",
                        "## Rotation Playbook",
                        "",
                        "Rotate immediately on suspected leak. The rotation command:",
                        "",
                        "```bash",
                        "mcp rotate-token",
                        "```",
                        "",
                        "It invalidates the previous token, writes the "
                        "new one to `~/.enderai_mcp_token`, and prints "
                        "the fresh-terminal reminder.",
                        "",
                        "Manual rotation (when the CLI is not available):",
                        "",
                        "1. log in to the EnderAI dashboard",
                        "2. revoke the existing token",
                        "3. create a new token with the same scope",
                        "4. paste it into `~/.enderai_mcp_token` (0600 permissions)",
                        "5. open a fresh terminal",
                        "6. run `mcp whoami` to confirm",
                        "",
                        "Default TTL is 30 days. Tokens beyond that "
                        "TTL stop working server-side regardless of "
                        "client state.",
                    ]
                ),
            },
            {
                "anchor_id": "shared-machines",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: shared-machines -->",
                        "## Shared Machines And CI Runners",
                        "",
                        "On shared machines and CI runners, single-"
                        "tenant scoped tokens are required.",
                        "",
                        "Reasons:",
                        "",
                        "- a leak on a shared machine should not "
                        "compromise other tenants",
                        "- scoped tokens narrow blast radius if the "
                        "shared machine is compromised",
                        "- CI runs often retain logs that may leak a "
                        "token if not properly masked; narrow scope "
                        "limits damage",
                        "",
                        "CI integration:",
                        "",
                        "- GitHub Actions: store the token in an "
                        "encrypted secret and reference it as "
                        "`${{ secrets.ENDERAI_MCP_TOKEN }}`",
                        "- GitLab CI: store the token as a masked protected variable",
                        "- both flows inject the token into the "
                        "environment without writing it to disk",
                    ]
                ),
            },
            {
                "anchor_id": "v2-instructions",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: v2-instructions -->",
                        "## V2 Instruction Set",
                        "",
                        "V2-enabled users receive instructions to "
                        "prefer the Taskforce V2 document toolset, "
                        "create a document at the start of meaningful "
                        "work, and maintain Summary and Details "
                        "document views.",
                        "",
                        "Expected agent behavior:",
                        "",
                        "- create a Taskforce document at the start of meaningful work",
                        "- update the document as files, links, "
                        "commands, decisions, and outcomes develop",
                        "- keep the Summary concise and useful for a human reader",
                        "- keep Details as a markdown context file "
                        "that an AI agent can ingest later",
                        "- finalize the document when the work completes or stops",
                        "",
                        "The agent never touches the legacy "
                        "case-and-topic model on a V2 account, even "
                        "if it has the credentials to do so.",
                    ]
                ),
            },
            {
                "anchor_id": "lifecycle",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: lifecycle -->",
                        "## Document Lifecycle",
                        "",
                        "The lifecycle rules are deliberately short.",
                        "",
                        "1. **Create** — at the start of a unit of "
                        "work that is worth capturing, before doing "
                        "anything destructive",
                        "2. **Update** — every time a meaningful "
                        "fact lands (file changed, decision taken, "
                        "command run, outcome observed)",
                        "3. **Finalize** — when the work stops, "
                        "whether or not it succeeded; finalization "
                        "is just a save that brings the Summary into "
                        "line with the current state",
                        "",
                        "A document that has been finalized can still "
                        "be edited; finalize is not a lock. The "
                        "intent is to mark a coherent point in time.",
                    ]
                ),
            },
            {
                "anchor_id": "troubleshooting",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: troubleshooting -->",
                        "## Troubleshooting",
                        "",
                        "The four common failure modes:",
                        "",
                        "- **stale shell** — the environment has an "
                        "older token. Diagnostic: `echo "
                        "$ENDERAI_MCP_TOKEN` differs from "
                        "`cat ~/.enderai_mcp_token`. Fix: open a "
                        "new terminal.",
                        "- **expired token** — server rejects the "
                        "token. Diagnostic: `mcp whoami` returns "
                        "an `expired` error. Fix: run the rotation "
                        "flow.",
                        "- **network egress** — the client cannot "
                        "reach the MCP endpoint. Diagnostic: "
                        "`curl -fsS https://mcp.enderai.com/health` "
                        "fails. Fix: confirm corporate proxy / "
                        "firewall allows traffic to the MCP host.",
                        "- **clock skew** — the client clock is more "
                        "than five minutes off; signed requests "
                        "fail. Diagnostic: compare local time with "
                        "an NTP source. Fix: re-sync NTP.",
                        "",
                        "Canonical first step for any of these: "
                        "open a new terminal. It catches stale "
                        "shell and several flavours of cached "
                        "client state.",
                    ]
                ),
            },
            {
                "anchor_id": "anti-patterns",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: anti-patterns -->",
                        "## Anti-Patterns",
                        "",
                        "Do not:",
                        "",
                        "- commit `~/.enderai_mcp_token` to a repo",
                        "- paste tokens into chat, email, or screenshots",
                        "- share a single token across multiple "
                        "operators (use one token per operator so "
                        "rotation has narrow blast radius)",
                        "- store the token in a shared password "
                        "manager entry where audit logging is weak",
                        "- write the token to a build artifact, "
                        "container image, or documentation example",
                        "",
                        "Any of these requires immediate rotation. "
                        "The rotation command is intentionally fast "
                        "so the response to a leak is always a "
                        "single command away.",
                    ]
                ),
            },
            {
                "anchor_id": "commands",
                "markdown": "\n".join(
                    [
                        "<!-- evidence-anchor: commands -->",
                        "## Commands Run",
                        "",
                        "```bash",
                        "mcp whoami",
                        "mcp rotate-token",
                        "ls -l ~/.enderai_mcp_token",
                        "curl -fsS https://mcp.enderai.com/health",
                        "```",
                        "",
                        "## Open Follow-Up",
                        "",
                        "- Ship a `mcp doctor` subcommand that runs "
                        "all four troubleshooting diagnostics in "
                        "one call",
                        "- Add an automatic stale-shell detector "
                        "that compares `$ENDERAI_MCP_TOKEN` with "
                        "the file content on shell prompt",
                        "- Publish the CI integration recipes as a "
                        "standalone doc once we have one happy "
                        "customer on each (GitHub Actions and "
                        "GitLab CI)",
                    ]
                ),
            },
        ],
    },
    # -----------------------------------------------------------------
    # Stripe webhook idempotency trio (TF-191, demo video)
    #
    # Three linked docs that surface together on the demo prompt
    # "Stripe is double-charging some users on plan upgrades…"
    # See ~/dev/docs/taskforce-agents-demo-handoff.md §3 for design
    # rationale and ~/dev/docs/taskforce-demo-video-plan.md §5 for the
    # rediscovery-cost math (~$0.38 savings target).
    #
    # IMPORTANT credibility framing: the incident-2026-04-11 section
    # says "baseline webhook replay coverage existed but did not cover
    # this newer plan-upgrade fulfillment path" — NOT "we added a
    # replay test." That framing matches TF-193's renamed regression
    # test (`test_plan_upgrade_webhook_retry_short_circuits_before_dispatch`)
    # and keeps the demo narration honest.
    # -----------------------------------------------------------------
    {
        "title": "Stripe webhook idempotency strategy",
        "description": (
            "How we dedupe Stripe webhook retries so plan upgrades "
            "don't double-fulfill. Decision record + WAL table design."
        ),
        "created_at": _dt(2026, 4, 12),
        "updated_at": _dt(2026, 4, 27),
        "collaborators": ["Alex Lee", "Codex"],
        "ai_generated_summary": (
            "Inbound Stripe webhooks are deduped via a "
            "stripe_webhook_event WAL table keyed on event_id and "
            "is_test_mode. billing.py checks the WAL before dispatching "
            "to handlers; duplicates return 200 OK without re-running "
            "fulfillment. Baseline replay coverage exists, but newer "
            "event-specific fulfillment paths still need targeted "
            "regression tests."
        ),
        "human_summary": (
            "Stripe retries webhook delivery on non-2xx responses and "
            "can redeliver events during service recovery. After the "
            "2026-04-11 Pro upgrade double-charge incident, we captured "
            "the invariant: inbound Stripe events must be deduped at "
            "the route boundary before fulfillment. Baseline replay "
            "coverage exists; newer plan-upgrade paths still need "
            "targeted regression tests (see "
            "stripe-plan-upgrade-regression-coverage)."
        ),
        "main_body": [
            {
                "segments": [
                    {
                        "text": (
                            "Stripe may redeliver webhook events. "
                            "Inbound handlers must be idempotent at "
                            "the route boundary."
                        ),
                        "evidence_anchor_id": "decision-wal-table",
                    }
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "The stripe_webhook_event WAL must be "
                            "written before fulfillment dispatch, not "
                            "after."
                        ),
                        "evidence_anchor_id": "decision-wal-table",
                    }
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "Baseline replay tests cover duplicate "
                            "delivery, but event-specific side effects "
                            "need targeted regression coverage."
                        ),
                        "evidence_anchor_id": "targeted-regression-test",
                    }
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "Test-mode and live-mode events must be "
                            "scoped separately via event.livemode / "
                            "is_test_mode."
                        ),
                        "evidence_anchor_id": "gotcha-test-vs-live",
                    }
                ]
            },
        ],
        "details_file_name": "stripe-webhook-idempotency.details.md",
        "details_markdown_sections": [
            {
                "anchor_id": "decision-wal-table",
                "markdown": (
                    "## Decision — WAL table at the route boundary\n\n"
                    "**Chose:** dedicated `stripe_webhook_event` WAL "
                    "table, checked in `app/api/routes/billing.py` "
                    "BEFORE dispatching to any handler.\n\n"
                    "**Why:** fulfillment handlers are not uniformly "
                    "idempotent. Some webhook types, such as "
                    "`customer.subscription.updated`, do not have a "
                    "natural unique side-effect key across all upgrade "
                    "paths.\n\n"
                    "**Ruled out:**\n"
                    "- In-handler dedupe with `ON CONFLICT DO NOTHING` "
                    "on fulfillment rows.\n"
                    "- Redis SETNX with TTL in the payment critical "
                    "path.\n"
                    "- Trusting Stripe's `Idempotency-Key` header, "
                    "which applies to outbound Stripe API calls, not "
                    "inbound webhooks.\n\n"
                    "**Files:**\n"
                    "- `app/api/routes/billing.py`\n"
                    "- `app/core/stripe_billing.py`\n"
                    "- `app/models.py`\n"
                    "- `app/alembic/versions/*stripe_webhook_wal*.py`\n"
                ),
            },
            {
                "anchor_id": "incident-2026-04-11",
                "markdown": (
                    "## Incident — 2026-04-11 double-charge\n\n"
                    "30 customers on Pro upgrades got charged twice "
                    "over a 90-minute window. Root cause: Stripe "
                    "aggressively retried webhook delivery during "
                    "recovery, and our upgrade flow ran twice for the "
                    "same event.\n\n"
                    "**Symptoms:**\n"
                    "- Duplicate invoices for the same "
                    "`subscription_id`\n"
                    "- Sentry spike on "
                    "`stripe.upgrade.duplicate_invoice`\n"
                    "- Customer-facing: two charges in the same "
                    "billing cycle\n\n"
                    "**Resolution:**\n"
                    "- Hotfix: voided duplicate invoices and refunded "
                    "affected charges\n"
                    "- Followup: added the WAL table plus baseline "
                    "webhook replay coverage\n\n"
                    "**Important nuance:** the baseline replay test "
                    "verified duplicate delivery at the webhook "
                    "boundary, but did not assert every newer "
                    "downstream fulfillment side effect. Newer "
                    "event-specific fulfillment paths — particularly "
                    "`customer.subscription.updated` plan upgrades — "
                    "still need targeted regression tests that prove "
                    "the side effect ran exactly once. See "
                    "`stripe-plan-upgrade-regression-coverage` for the "
                    "current pattern.\n"
                ),
            },
            {
                "anchor_id": "targeted-regression-test",
                "markdown": (
                    "## Test guidance — plan-upgrade replay "
                    "regression\n\n"
                    "Baseline replay coverage is not enough for "
                    "billing changes. For plan upgrades, the "
                    "regression test must assert that a duplicate "
                    "`customer.subscription.updated` event does not "
                    "re-fire fulfillment.\n\n"
                    "Preferred test name:\n\n"
                    "```text\n"
                    "test_plan_upgrade_webhook_retry_short_circuits_before_dispatch\n"
                    "```\n\n"
                    "The test should:\n"
                    "1. POST the same signed Stripe plan-upgrade "
                    "webhook twice.\n"
                    "2. Assert both responses are successful.\n"
                    "3. Assert the plan-upgrade fulfillment side "
                    "effect ran exactly once.\n"
                    "4. Assert duplicate delivery returns before "
                    "`_dispatch_event()`.\n"
                ),
            },
            {
                "anchor_id": "gotcha-test-vs-live",
                "markdown": (
                    "## Gotcha — test mode vs live mode events\n\n"
                    "Stripe webhooks fire in both live and test mode. "
                    "We scope WAL rows by `(event_id, is_test_mode)` "
                    "so test-mode replays cannot collide with live "
                    "fulfillment.\n\n"
                    "Use `event.livemode` from the payload, not log "
                    "text or event id prefixes, when deciding whether "
                    "the event is test or live.\n"
                ),
            },
        ],
    },
    {
        "title": "Debugging Stripe webhook retries and double-fire fulfillment",
        "description": (
            "Playbook for replaying webhooks, reading the WAL, and "
            "diagnosing duplicate delivery."
        ),
        "created_at": _dt(2026, 4, 14),
        "updated_at": _dt(2026, 5, 2),
        "collaborators": ["Alex Lee"],
        "ai_generated_summary": (
            "Use Stripe CLI event replay to reproduce delivery flakes. "
            "Check the WAL for `(event_id, is_test_mode)`, confirm the "
            "route short-circuits before dispatch, and inspect "
            "event.livemode when logs are ambiguous."
        ),
        "human_summary": (
            "Operational playbook for Stripe webhook flakes. Covers "
            "replaying events with the Stripe CLI, reading "
            "stripe_webhook_event, interpreting dedup hits, checking "
            "test/live mode, and distinguishing duplicate delivery "
            "from non-idempotent fulfillment."
        ),
        "main_body": [
            {
                "segments": [
                    {
                        "text": (
                            "If Stripe double-fires a webhook, first "
                            "check whether the WAL short-circuits "
                            "before fulfillment dispatch."
                        ),
                        "evidence_anchor_id": "repro-with-stripe-cli",
                    }
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "A dedup hit should return 200 without "
                            "re-running the fulfillment path."
                        ),
                        "evidence_anchor_id": "dedup-hit-log",
                    }
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "Test-mode events look similar to live "
                            "events in logs; check event.livemode."
                        ),
                        "evidence_anchor_id": "test-mode-trap",
                    }
                ]
            },
        ],
        "details_file_name": "debugging-stripe-webhooks.details.md",
        "details_markdown_sections": [
            {
                "anchor_id": "repro-with-stripe-cli",
                "markdown": (
                    "## Reproducing webhook retries that double-fire\n\n"
                    "Start by reading `app/api/routes/billing.py` to "
                    "confirm the WAL short-circuit runs before "
                    "`_dispatch_event`. Then replay an event with the "
                    "Stripe CLI:\n\n"
                    "```bash\n"
                    "stripe events list --limit 10\n"
                    "stripe events resend evt_1OabcD2eZvKYlo2C0X8YzABC\n"
                    "heroku logs -t -a enderai-backend "
                    "| grep stripe.webhook\n"
                    "```\n\n"
                    "Expected duplicate behavior on a healthy build: "
                    "the second webhook retry returns 200 and logs a "
                    "dedup hit before any fulfillment handler runs. If "
                    "the plan upgrade side effect runs twice, "
                    "`record_stripe_event_or_skip` in "
                    "`app/core/stripe_billing.py` is being called too "
                    "late in the route.\n"
                ),
            },
            {
                "anchor_id": "dedup-hit-log",
                "markdown": (
                    "## Expected duplicate log line\n\n"
                    "```text\n"
                    "stripe.webhook.dedup_hit "
                    "event_id=evt_1OabcD2eZvKYlo2C0X8YzABC\n"
                    "  is_test_mode=False "
                    "processed_at_age_seconds=3.2\n"
                    "```\n\n"
                    "If the fulfillment log appears after this line on "
                    "duplicate delivery, the route is not "
                    "short-circuiting correctly.\n"
                ),
            },
            {
                "anchor_id": "test-mode-trap",
                "markdown": (
                    "## Test mode vs live mode\n\n"
                    "Always inspect `event.livemode`. Test-mode events "
                    "can be replayed from local machines and should "
                    "never suppress live fulfillment.\n"
                ),
            },
        ],
    },
    {
        "title": "Stripe plan upgrade webhook retries — regression test pattern",
        "description": (
            "Test strategy for Stripe plan-upgrade side effects under webhook replay."
        ),
        "created_at": _dt(2026, 5, 3),
        "updated_at": _dt(2026, 5, 18),
        "collaborators": ["Alex Lee", "Claude"],
        "ai_generated_summary": (
            "For plan upgrades, duplicate "
            "`customer.subscription.updated` delivery must not re-run "
            "entitlement or invoice side effects. The regression test "
            "should patch the fulfillment path or assert persisted "
            "side effects ran exactly once."
        ),
        "human_summary": (
            "Guide for writing billing replay tests that assert "
            "downstream side effects, not just successful HTTP "
            "responses. Created after we realized baseline webhook "
            "replay tests can miss event-specific fulfillment paths."
        ),
        "main_body": [
            {
                "segments": [
                    {
                        "text": (
                            "Billing replay tests should assert "
                            "fulfillment side effects ran once, not "
                            "just that the route returned 200."
                        ),
                        "evidence_anchor_id": "side-effect-assertion",
                    }
                ]
            },
            {
                "segments": [
                    {
                        "text": (
                            "Plan-upgrade paths are high-risk because "
                            "subscription updates can trigger "
                            "entitlement, invoice, and tier changes."
                        ),
                        "evidence_anchor_id": "plan-upgrade-risk",
                    }
                ]
            },
        ],
        "details_file_name": "stripe-plan-upgrade-regression.details.md",
        "details_markdown_sections": [
            {
                "anchor_id": "side-effect-assertion",
                "markdown": (
                    "## Side-effect assertion\n\n"
                    "A passing duplicate replay test should prove the "
                    "handler in `app/api/routes/billing.py` did not "
                    "re-run the expensive or customer-visible side "
                    "effect, even when Stripe webhook retries fire "
                    "twice for the same `customer.subscription.updated` "
                    "plan upgrade event.\n\n"
                    "Acceptable assertions for the regression test in "
                    "`app/tests/api/routes/test_billing.py`:\n"
                    "- fulfillment function in "
                    "`app/core/stripe_billing.py` called once\n"
                    "- entitlement row written once\n"
                    "- invoice adjustment created once\n"
                    "- tier transition recorded once\n"
                ),
            },
            {
                "anchor_id": "plan-upgrade-risk",
                "markdown": (
                    "## Why plan upgrades need targeted coverage\n\n"
                    "`customer.subscription.updated` can represent "
                    "many state changes. A generic webhook replay test "
                    "may pass while a newly-added upgrade branch "
                    "still re-fires fulfillment. Always include a "
                    "test that uses the exact event shape for the "
                    "upgrade path.\n"
                ),
            },
            {
                "anchor_id": "targeted-regression-test",
                "markdown": (
                    "## The targeted test\n\n"
                    "```text\n"
                    "tests/api/routes/test_billing.py::"
                    "test_plan_upgrade_webhook_retry_short_circuits_before_dispatch\n"
                    "```\n\n"
                    "Pattern:\n\n"
                    "1. Build a Stripe `customer.subscription.updated` "
                    "event for a plan upgrade.\n"
                    "2. Patch (or observe) the plan-upgrade "
                    "fulfillment function.\n"
                    "3. POST the same signed payload twice.\n"
                    "4. Assert the fulfillment function was called "
                    "exactly once across both deliveries.\n"
                ),
            },
        ],
    },
]


def _demo_agent_doc(
    *,
    slug: str,
    title: str,
    description: str,
    human_summary: str,
    ai_generated_summary: str,
    main_body: list[dict[str, str]],
    details_markdown_sections: list[dict[str, str]],
    created_at: datetime,
    specialist: str,
) -> dict[str, Any]:
    return {
        "slug": slug,
        "specialist": specialist,
        "title": title,
        "description": description,
        "created_at": created_at,
        "updated_at": _dt(2026, 5, 24),
        "collaborators": ["Alex Lee", "Codex"],
        "ai_generated_summary": ai_generated_summary,
        "human_summary": human_summary,
        "main_body": [
            {
                "segments": [
                    {
                        "text": item["text"],
                        "evidence_anchor_id": item["evidence_anchor_id"],
                    }
                ]
            }
            for item in main_body
        ],
        "details_file_name": f"{slug}.details.md",
        "details_markdown_sections": details_markdown_sections,
    }


# TF-198 demo specialist supporting docs. Jensen's three Stripe documents live
# in DEMO_SEED above (TF-191); these twelve make the rest of the Agents grid
# credible when the demoer clicks into non-billing specialists.
DEMO_AGENT_SUPPORTING_SEED: list[dict[str, Any]] = [
    _demo_agent_doc(
        slug="search-indexer-drift-sweep-design",
        specialist="mira",
        title="Search indexer drift-sweep design",
        description=(
            "How the V2 document indexer detects stale embeddings and "
            "refreshes source_item_embedding rows."
        ),
        human_summary=(
            "The search indexer runs as an async task in the FastAPI process. "
            "It detects documents whose index markers are missing, stale, or "
            "on an old index version, then rebuilds summary and details "
            "chunks for embedding."
        ),
        ai_generated_summary=(
            "Drift is detected from last_indexed_at, updated_at, and "
            "index_version. DocumentSource emits one summary chunk plus "
            "details-anchor chunks."
        ),
        created_at=_dt(2026, 4, 21),
        main_body=[
            {
                "text": (
                    "The drift sweep is the source of truth for deciding "
                    "when a V2 document needs re-indexing."
                ),
                "evidence_anchor_id": "drift-sweep-loop",
            },
            {
                "text": (
                    "Long details sections fan out into multiple chunks but "
                    "keep their parent anchor link."
                ),
                "evidence_anchor_id": "chunking-anchor-contract",
            },
        ],
        details_markdown_sections=[
            {
                "anchor_id": "drift-sweep-loop",
                "markdown": (
                    "## Drift sweep loop\n\n"
                    "The indexer selects documents where `last_indexed_at` "
                    "is null, older than `updated_at`, or where "
                    "`index_version` no longer matches the current document "
                    "indexer version."
                ),
            },
            {
                "anchor_id": "chunking-anchor-contract",
                "markdown": (
                    "## Chunking and anchor contract\n\n"
                    "Each document emits a synthetic summary chunk plus one "
                    "or more details chunks. If a details section is long, "
                    "it may fan out into `anchor#1`, `anchor#2`, etc., but "
                    "the UI should still link back to the original details "
                    "anchor."
                ),
            },
        ],
    ),
    _demo_agent_doc(
        slug="pgvector-acl-retrieval-gotchas",
        specialist="mira",
        title="pgvector retrieval and ACL gotchas",
        description=(
            "Why a relevant document can be missing from search results and "
            "how to debug ACL-filtered retrieval."
        ),
        human_summary=(
            "Search retrieval joins embeddings back to V2 documents and "
            "applies the same ACL filter as document reads. A good embedding "
            "hit can disappear if ownership, organization, share, or demo "
            "flags do not match."
        ),
        ai_generated_summary=(
            "Debug search misses by checking embedding existence, document "
            "ACL, organization visibility, explicit shares, and demo "
            "isolation."
        ),
        created_at=_dt(2026, 4, 22),
        main_body=[
            {
                "text": (
                    "ACL is double-enforced: embeddings carry denormalized "
                    "access fields, but retrieval also joins back to "
                    "V2Document."
                ),
                "evidence_anchor_id": "acl-double-enforcement",
            }
        ],
        details_markdown_sections=[
            {
                "anchor_id": "acl-double-enforcement",
                "markdown": (
                    "## ACL double enforcement\n\n"
                    "Retrieval filters candidate embeddings, then joins "
                    "back to V2Document and applies document ACL. This "
                    "means ACL changes take effect without re-embedding the "
                    "document."
                ),
            },
            {
                "anchor_id": "demo-isolation",
                "markdown": (
                    "## Demo isolation\n\n"
                    "Demo documents and live user documents should be "
                    "isolated in both document reads and search retrieval."
                ),
            },
        ],
    ),
    _demo_agent_doc(
        slug="citation-anchor-fanout-playbook",
        specialist="mira",
        title="Citation anchor fanout playbook",
        description=(
            "How to preserve inspectable citations when details sections are "
            "split into multiple chunks."
        ),
        human_summary=(
            "Search citations must remain inspectable even when long details "
            "sections are split for embeddings. Chunks can fan out "
            "internally, but the user should land on the canonical evidence "
            "anchor."
        ),
        ai_generated_summary=(
            "Preserve source transparency by mapping chunk-level hits back "
            "to document detail anchors. Avoid sending users to opaque chunk "
            "ids."
        ),
        created_at=_dt(2026, 4, 23),
        main_body=[
            {
                "text": (
                    "Citation links should land on canonical details "
                    "anchors, not internal chunk ids."
                ),
                "evidence_anchor_id": "long-section-anchor-fanout",
            }
        ],
        details_markdown_sections=[
            {
                "anchor_id": "long-section-anchor-fanout",
                "markdown": (
                    "## Long-section anchor fanout\n\n"
                    "If a details section exceeds the chunk size, the "
                    "indexer may create several embedding chunks. The "
                    "user-facing citation should still point to the parent "
                    "details anchor."
                ),
            }
        ],
    ),
    _demo_agent_doc(
        slug="claude-code-taskforce-hook-setup",
        specialist="orin",
        title="Claude Code Taskforce hook setup",
        description=(
            "How Claude Code hooks call Taskforce before and after an agent session."
        ),
        human_summary=(
            "Claude Code can call Taskforce through local hooks. "
            "UserPromptSubmit runs discovery synchronously before Claude "
            "sees the prompt. PostToolUse and Stop can send checkpoints and "
            "final observations."
        ),
        ai_generated_summary=(
            "Hook setup depends on a valid agent bearer token, local "
            "scripts, and endpoint reachability. Keep UserPromptSubmit fast "
            "because it is on the prompt path."
        ),
        created_at=_dt(2026, 4, 24),
        main_body=[
            {
                "text": (
                    "UserPromptSubmit calls /v2/taskforce/discover before "
                    "Claude sees the prompt."
                ),
                "evidence_anchor_id": "userpromptsubmit-flow",
            },
            {
                "text": "Stop hook sends the final observation for material sessions.",
                "evidence_anchor_id": "stop-observe-flow",
            },
        ],
        details_markdown_sections=[
            {
                "anchor_id": "userpromptsubmit-flow",
                "markdown": (
                    "## UserPromptSubmit flow\n\n"
                    "The hook captures prompt, cwd, recent files, and "
                    "branch. It calls Taskforce discovery with a short "
                    "timeout and prepends related context before Claude "
                    "Code processes the user's request."
                ),
            },
            {
                "anchor_id": "stop-observe-flow",
                "markdown": (
                    "## Stop observe flow\n\n"
                    "At session end, the hook sends a final observation. "
                    "Material sessions can record usage, update documents, "
                    "and append referenced-by entries."
                ),
            },
        ],
    ),
    _demo_agent_doc(
        slug="hosted-mcp-session-lifecycle",
        specialist="orin",
        title="Hosted MCP session lifecycle",
        description=(
            "How the MCP bridge validates agent tokens, binds sessions, and "
            "forwards Taskforce tool calls."
        ),
        human_summary=(
            "The hosted MCP bridge is a protocol adapter. It validates the "
            "incoming bearer token, binds the backend token to an MCP "
            "session, and forwards tools through authenticated backend "
            "requests."
        ),
        ai_generated_summary=(
            "MCP sessions are keyed by Mcp-Session-Id and carry a token "
            "reference. The bridge is not a source of truth; it forwards to "
            "FastAPI."
        ),
        created_at=_dt(2026, 4, 25),
        main_body=[
            {
                "text": (
                    "The MCP bridge validates agent credentials before "
                    "forwarding backend calls."
                ),
                "evidence_anchor_id": "streamable-http-session-map",
            }
        ],
        details_markdown_sections=[
            {
                "anchor_id": "streamable-http-session-map",
                "markdown": (
                    "## Streamable HTTP session map\n\n"
                    "Each MCP request carries authorization. After "
                    "validation, the server stores transport, server, and "
                    "token reference under the MCP session id so subsequent "
                    "tool calls can forward with the right bearer."
                ),
            },
            {
                "anchor_id": "taskforce-mcp-tools",
                "markdown": (
                    "## Taskforce MCP tools\n\n"
                    "Hookless clients can call `taskforce_session_start`, "
                    "`taskforce_session_observe`, `taskforce_session_log`, "
                    "and `taskforce_discover`."
                ),
            },
        ],
    ),
    _demo_agent_doc(
        slug="agent-credential-rotation-playbook",
        specialist="orin",
        title="Agent credential rotation playbook",
        description=(
            "How to safely rotate, revoke, and debug Taskforce agent credentials."
        ),
        human_summary=(
            "Agent credentials are backend JWTs bound to a credential id and "
            "token version. Rotating or revoking invalidates old tokens and "
            "may require updating local MCP or hook config."
        ),
        ai_generated_summary=(
            "Debug token failures by checking credential version, "
            "revoked_at, local config, and whether the token kind is "
            "agent_mcp."
        ),
        created_at=_dt(2026, 4, 26),
        main_body=[
            {
                "text": (
                    "Revoked or rotated credentials should fail validation "
                    "even if the JWT has not expired."
                ),
                "evidence_anchor_id": "revoke-rotate-debug",
            }
        ],
        details_markdown_sections=[
            {
                "anchor_id": "revoke-rotate-debug",
                "markdown": (
                    "## Revoke and rotate debugging\n\n"
                    "Check:\n"
                    "- credential exists\n"
                    "- token version matches\n"
                    "- revoked_at is null\n"
                    "- token_kind is `agent_mcp`\n"
                    "- local hook or MCP config uses the latest token"
                ),
            }
        ],
    ),
    _demo_agent_doc(
        slug="taskforce-session-savings-math",
        specialist="vega",
        title="Taskforce session savings math",
        description=(
            "How session-level avoided rediscovery tokens and USD savings "
            "are calculated."
        ),
        human_summary=(
            "Session savings are derived from consulted documents. For each "
            "document, net saved tokens equal rediscovery_cost_tokens minus "
            "the summary/context tokens actually read."
        ),
        ai_generated_summary=(
            "Avoided rediscovery is a structural estimate cached on "
            "documents and reduced by consultation cost. The demo should "
            "show the same number in chat and on the session-scoped metrics "
            "page."
        ),
        created_at=_dt(2026, 4, 27),
        main_body=[
            {
                "text": (
                    "Session savings equal rediscovery cost minus "
                    "consultation cost for consulted documents."
                ),
                "evidence_anchor_id": "rediscovery-minus-consult",
            }
        ],
        details_markdown_sections=[
            {
                "anchor_id": "rediscovery-minus-consult",
                "markdown": (
                    "## Rediscovery minus consultation\n\n"
                    "```text\n"
                    "net_saved_tokens = max(0, rediscovery_cost_tokens - "
                    "consult_token_cost)\n"
                    "```"
                ),
            },
            {
                "anchor_id": "pricing-snapshot",
                "markdown": (
                    "## Pricing snapshot\n\n"
                    "The USD calculation should use the model pricing row "
                    "that was effective when the event was recorded."
                ),
            },
        ],
    ),
    _demo_agent_doc(
        slug="metrics-event-rollup-architecture",
        specialist="vega",
        title="Metrics event rollup architecture",
        description="Event-sourced metric recording, pricing snapshots, and daily rollups.",
        human_summary=(
            "Metrics are stored as append-only events. A registry defines "
            "public metric names, daily rollups materialize aggregates, and "
            "composed metrics are calculated on read."
        ),
        ai_generated_summary=(
            "Write raw metric events first, snapshot pricing at write time, "
            "and roll up by day, user, org, and demo flag."
        ),
        created_at=_dt(2026, 4, 28),
        main_body=[
            {
                "text": (
                    "Pricing is snapshotted at write time so historical USD "
                    "totals remain stable."
                ),
                "evidence_anchor_id": "pricing-snapshot-at-write",
            }
        ],
        details_markdown_sections=[
            {
                "anchor_id": "pricing-snapshot-at-write",
                "markdown": (
                    "## Pricing snapshot at write\n\n"
                    "Each metrics event stores a reference to the pricing "
                    "row used to compute USD."
                ),
            },
            {
                "anchor_id": "demo-live-isolation",
                "markdown": (
                    "## Demo and live isolation\n\n"
                    "Rollups include `is_demo` in their key so seeded demo "
                    "activity never pollutes live user metrics."
                ),
            },
        ],
    ),
    _demo_agent_doc(
        slug="demo-metrics-page-session-filter",
        specialist="vega",
        title="Demo metrics page session filter",
        description=(
            "How the demo links from a completed Taskforce session into a "
            "scoped metrics view."
        ),
        human_summary=(
            "The demo savings line should link to a metrics page scoped by "
            "session_id. The page should show documents consulted, "
            "estimated rediscovery cost, consultation cost, net tokens "
            "saved, and USD saved."
        ),
        ai_generated_summary=(
            "Use `/v2/metrics?session_id=<uuid>` for the video. Show a "
            "banner that the page is filtered to one session, with a link "
            "back to all metrics."
        ),
        created_at=_dt(2026, 4, 29),
        main_body=[
            {
                "text": (
                    "The metrics page should make the chat savings number inspectable."
                ),
                "evidence_anchor_id": "session-id-query-param",
            }
        ],
        details_markdown_sections=[
            {
                "anchor_id": "session-id-query-param",
                "markdown": (
                    "## Session id query param\n\n"
                    "The video should link to:\n\n"
                    "```text\n"
                    "/v2/metrics?session_id=<session_id>\n"
                    "```"
                ),
            }
        ],
    ),
    _demo_agent_doc(
        slug="evidence-anchor-authoring-guide",
        specialist="nia",
        title="Evidence anchor authoring guide",
        description=(
            "How to write Taskforce details sections that agents can cite "
            "and users can inspect."
        ),
        human_summary=(
            "Good Taskforce documents use specific anchors for decisions, "
            "incidents, gotchas, and verification steps. Agents should link "
            "to anchors, not just whole documents."
        ),
        ai_generated_summary=(
            "Use stable, human-readable anchor ids. Keep decision sections "
            "separate from incident sections and verification steps."
        ),
        created_at=_dt(2026, 4, 30),
        main_body=[
            {
                "text": (
                    "Anchor names should be stable and explain what the "
                    "user will see when clicked."
                ),
                "evidence_anchor_id": "anchor-naming-rules",
            }
        ],
        details_markdown_sections=[
            {
                "anchor_id": "anchor-naming-rules",
                "markdown": (
                    "## Anchor naming rules\n\n"
                    "Prefer IDs like:\n"
                    "- `decision-wal-table`\n"
                    "- `incident-2026-04-11`\n"
                    "- `gotcha-test-vs-live`\n"
                    "- `verifying-the-fix`"
                ),
            }
        ],
    ),
    _demo_agent_doc(
        slug="referenced-by-update-policy",
        specialist="nia",
        title="Referenced-by update policy",
        description=(
            "When Taskforce should append usage back to a document after an "
            "agent session."
        ),
        human_summary=(
            "Referenced-by entries close the loop after reuse. They show "
            "that a document was not just stored but actively helped solve "
            "later work."
        ),
        ai_generated_summary=(
            "Add referenced-by entries after material sessions that "
            "consulted a doc and used it to make a decision, fix, or test."
        ),
        created_at=_dt(2026, 5, 1),
        main_body=[
            {
                "text": (
                    "Referenced-by entries make reuse visible and strengthen "
                    "future routing signals."
                ),
                "evidence_anchor_id": "close-the-loop",
            }
        ],
        details_markdown_sections=[
            {
                "anchor_id": "close-the-loop",
                "markdown": (
                    "## Close the loop\n\n"
                    "After a material session uses a document, append:\n"
                    "- session title or prompt summary\n"
                    "- date\n"
                    "- files touched\n"
                    "- outcome\n"
                    "- token savings if available"
                ),
            }
        ],
    ),
    _demo_agent_doc(
        slug="document-reuse-vs-create-playbook",
        specialist="nia",
        title="Document reuse vs create playbook",
        description=(
            "How Taskforce decides whether to patch an existing document or "
            "create a new one."
        ),
        human_summary=(
            "Reusing the right document preserves continuity. Creating a "
            "new document is better when there are conflicting tenants, "
            "repos, outcomes, or a fundamentally different problem."
        ),
        ai_generated_summary=(
            "Prefer reuse when title, file, symbol, and intent signals "
            "align without conflicts. Create a new document when "
            "terminal-state, repo, tenant, or error-family conflicts fire."
        ),
        created_at=_dt(2026, 5, 2),
        main_body=[
            {
                "text": (
                    "Reuse decisions should consider both positive signals "
                    "and conflicts."
                ),
                "evidence_anchor_id": "reuse-decision-criteria",
            }
        ],
        details_markdown_sections=[
            {
                "anchor_id": "reuse-decision-criteria",
                "markdown": (
                    "## Reuse decision criteria\n\n"
                    "Reuse when:\n"
                    "- same repo\n"
                    "- same domain\n"
                    "- overlapping files or symbols\n"
                    "- no tenant conflict\n"
                    "- no terminal-state conflict"
                ),
            },
            {
                "anchor_id": "terminal-state-conflict",
                "markdown": (
                    "## Terminal-state conflict\n\n"
                    "A document with an outcome, finish marker, or "
                    "resolved incident should not be patched by unrelated "
                    "future work."
                ),
            },
        ],
    ),
]


def iter_demo_seed_catalog() -> list[dict[str, Any]]:
    return [*DEMO_SEED, *DEMO_AGENT_SUPPORTING_SEED]


def _share_public(session: Session, share: V2DocumentShare) -> V2DocumentSharePublic:
    user = session.get(User, share.user_id)
    return V2DocumentSharePublic(
        id=share.id,
        document_id=share.document_id,
        user_id=share.user_id,
        email=user.email if user else "unknown@example.com",
        full_name=user.full_name if user else None,
        permission=share.permission,  # type: ignore[arg-type]
        created_at=share.created_at,
        updated_at=share.updated_at,
    )


def list_v2_document_shares_public(
    session: Session, document_id: uuid.UUID
) -> list[V2DocumentSharePublic]:
    shares = session.exec(
        select(V2DocumentShare)
        .where(V2DocumentShare.document_id == document_id)
        .order_by(col(V2DocumentShare.updated_at).desc())
    ).all()
    return [_share_public(session, share) for share in shares]


def resolve_v2_document_access(
    session: Session, document: V2Document, actor: User, *, demo: bool
) -> str | None:
    if document.owner_id == actor.id:
        return "owner"
    if demo:
        return None
    if (
        document.visibility == "organization"
        and actor.organization_id is not None
        and document.organization_id == actor.organization_id
    ):
        return "editor"
    share = session.exec(
        select(V2DocumentShare)
        .where(V2DocumentShare.document_id == document.id)
        .where(V2DocumentShare.user_id == actor.id)
    ).first()
    if share:
        return share.permission
    return None


def can_update_v2_document(
    session: Session, document: V2Document, actor: User, *, demo: bool
) -> bool:
    return resolve_v2_document_access(session, document, actor, demo=demo) in {
        "owner",
        "editor",
    }


def build_v2_document_public(
    document: V2Document,
    *,
    session: Session | None = None,
    actor: User | None = None,
    demo: bool = False,
) -> V2DocumentPublic:
    folder_name: str | None = None
    shared_with: list[V2DocumentSharePublic] = []
    user_access = "owner"
    favorite: V2DocumentFavorite | None = None
    if session is not None:
        if document.folder_id is not None:
            folder = session.get(V2DocumentFolder, document.folder_id)
            folder_name = folder.name if folder else None
        shared_with = list_v2_document_shares_public(session, document.id)
        if actor is not None:
            user_access = (
                resolve_v2_document_access(session, document, actor, demo=demo)
                or "viewer"
            )
            favorite = session.exec(
                select(V2DocumentFavorite)
                .where(V2DocumentFavorite.document_id == document.id)
                .where(V2DocumentFavorite.user_id == actor.id)
            ).first()

    payload = document.model_dump()
    payload["folder_name"] = folder_name
    payload["shared_with"] = shared_with
    payload["user_access"] = user_access
    payload["is_favorite"] = favorite is not None if actor is not None else False
    return V2DocumentPublic.model_validate(payload)


def build_v2_document_folder_public(
    folder: V2DocumentFolder,
) -> V2DocumentFolderPublic:
    return V2DocumentFolderPublic.model_validate(folder, from_attributes=True)


def list_v2_documents_for_owner(
    session: Session, owner_id: uuid.UUID, *, demo: bool
) -> list[V2Document]:
    statement = (
        select(V2Document)
        .where(V2Document.owner_id == owner_id)
        .where(V2Document.is_demo.is_(demo))  # type: ignore[union-attr]
        .order_by(col(V2Document.updated_at).desc(), col(V2Document.created_at).desc())
    )
    return list(session.exec(statement).all())


def list_v2_documents_for_actor(
    session: Session, actor: User, *, demo: bool
) -> list[V2Document]:
    if demo or actor.organization_id is None:
        if demo:
            return list_v2_documents_for_owner(session, actor.id, demo=demo)
        shared_document_ids = select(V2DocumentShare.document_id).where(
            V2DocumentShare.user_id == actor.id
        )
        statement = (
            select(V2Document)
            .where(V2Document.is_demo.is_(False))  # type: ignore[union-attr]
            .where(
                or_(
                    V2Document.owner_id == actor.id,
                    col(V2Document.id).in_(shared_document_ids),
                )
            )
            .order_by(
                col(V2Document.updated_at).desc(), col(V2Document.created_at).desc()
            )
        )
        return list(session.exec(statement).all())

    shared_document_ids = select(V2DocumentShare.document_id).where(
        V2DocumentShare.user_id == actor.id
    )
    statement = (
        select(V2Document)
        .where(V2Document.is_demo.is_(False))  # type: ignore[union-attr]
        .where(
            or_(
                V2Document.owner_id == actor.id,
                col(V2Document.id).in_(shared_document_ids),
                and_(
                    V2Document.visibility == "organization",
                    V2Document.organization_id == actor.organization_id,
                ),
            )
        )
        .order_by(col(V2Document.updated_at).desc(), col(V2Document.created_at).desc())
    )
    return list(session.exec(statement).all())


def get_v2_document_for_owner(
    session: Session, owner_id: uuid.UUID, document_id: uuid.UUID
) -> V2Document | None:
    statement = (
        select(V2Document)
        .where(V2Document.id == document_id)
        .where(V2Document.owner_id == owner_id)
    )
    return session.exec(statement).first()


def build_v2_document_acl_filter(actor: User, *, demo: bool) -> Any:
    """SQLAlchemy filter expression for "documents this actor may read".

    Mirrors the historical 3-way OR (owner / explicit share / org-visible)
    plus the demo isolation rule. Centralized here so the V2 read path
    and the new Search retrieval (app/core/search/retrieval.py) stay in
    lockstep — any change to who-can-see-what flows through this one
    function instead of being duplicated across query sites.
    """

    if demo:
        return and_(
            V2Document.is_demo.is_(True),  # type: ignore[union-attr]
            V2Document.owner_id == actor.id,
        )

    shared_document_ids = select(V2DocumentShare.document_id).where(
        V2DocumentShare.user_id == actor.id
    )
    base = and_(
        V2Document.is_demo.is_(False),  # type: ignore[union-attr]
        or_(
            V2Document.owner_id == actor.id,
            col(V2Document.id).in_(shared_document_ids),
            and_(
                V2Document.visibility == "organization",
                V2Document.organization_id == actor.organization_id,
            )
            if actor.organization_id is not None
            else (V2Document.id.is_(None)),  # type: ignore[union-attr] -- always false
        ),
    )
    return base


def get_v2_document_for_actor(
    session: Session, actor: User, document_id: uuid.UUID, *, demo: bool
) -> V2Document | None:
    statement = (
        select(V2Document)
        .where(V2Document.id == document_id)
        .where(build_v2_document_acl_filter(actor, demo=demo))
    )
    return session.exec(statement).first()


def list_v2_document_folders_for_actor(
    session: Session, actor: User, *, demo: bool
) -> list[V2DocumentFolder]:
    if demo:
        statement = (
            select(V2DocumentFolder)
            .where(V2DocumentFolder.owner_id == actor.id)
            .where(V2DocumentFolder.is_demo.is_(True))  # type: ignore[union-attr]
            .order_by(col(V2DocumentFolder.name).asc())
        )
        return list(session.exec(statement).all())
    if actor.organization_id is None:
        statement = (
            select(V2DocumentFolder)
            .where(V2DocumentFolder.owner_id == actor.id)
            .where(V2DocumentFolder.is_demo.is_(False))  # type: ignore[union-attr]
            .order_by(col(V2DocumentFolder.name).asc())
        )
        return list(session.exec(statement).all())
    statement = (
        select(V2DocumentFolder)
        .where(V2DocumentFolder.is_demo.is_(False))  # type: ignore[union-attr]
        .where(
            or_(
                V2DocumentFolder.owner_id == actor.id,
                and_(
                    V2DocumentFolder.visibility == "organization",
                    V2DocumentFolder.organization_id == actor.organization_id,
                ),
            )
        )
        .order_by(col(V2DocumentFolder.name).asc())
    )
    return list(session.exec(statement).all())


def get_v2_document_folder_for_actor(
    session: Session, actor: User, folder_id: uuid.UUID, *, demo: bool
) -> V2DocumentFolder | None:
    statement = select(V2DocumentFolder).where(V2DocumentFolder.id == folder_id)
    statement = statement.where(V2DocumentFolder.is_demo.is_(demo))  # type: ignore[union-attr]
    if demo:
        statement = statement.where(V2DocumentFolder.owner_id == actor.id)
    elif actor.organization_id is None:
        statement = statement.where(V2DocumentFolder.owner_id == actor.id)
    else:
        statement = statement.where(
            or_(
                V2DocumentFolder.owner_id == actor.id,
                and_(
                    V2DocumentFolder.visibility == "organization",
                    V2DocumentFolder.organization_id == actor.organization_id,
                ),
            )
        )
    return session.exec(statement).first()


def apply_v2_document_update(document: V2Document, update: V2DocumentUpdate) -> bool:
    """Apply non-null fields of update to document. Returns True if anything changed."""
    fields_set = update.model_fields_set
    payload = update.model_dump(exclude_unset=True)
    # ``usage`` is metrics metadata, not document state; the caller records it
    # separately. Strip it before the setattr sweep.
    payload.pop("usage", None)
    if not payload:
        return False
    for field, value in payload.items():
        setattr(document, field, value)
    refresh_v2_document_token_counts(document)
    # If the caller explicitly set updated_at, trust it; otherwise stamp now.
    if "updated_at" not in fields_set:
        document.updated_at = get_datetime_utc()
    return True


def refresh_v2_document_token_counts(document: V2Document) -> None:
    """Recompute summary_tokens / details_tokens / rediscovery_cost_tokens.

    Idempotent and cheap (char-based heuristic + regex over details).
    Called after mutation so:
      * the reuse-savings estimator (plan §2.2 source 3) has fresh inputs
      * the Phase 3 ``avoided_rediscovery`` metric (TF-177) reflects
        current doc structure on every consultation
    """

    from app.core.metrics import (
        count_details_sections_tokens,
        count_paragraph_tokens,
    )
    from app.core.taskforce.rediscovery import compute_rediscovery_cost

    document.summary_tokens = count_paragraph_tokens(document.main_body)
    document.details_tokens = count_details_sections_tokens(
        document.details_markdown_sections
    )
    document.rediscovery_cost_tokens = compute_rediscovery_cost(document)


def ensure_v2_documents_demo_seed(session: Session, user: User) -> bool:
    """Lazily clone the demo catalog into the user's account.

    Idempotent by title so new catalog entries can be added for existing demo
    users without duplicating the documents they already have.
    """
    existing_titles = set(
        session.exec(
            select(V2Document.title)
            .where(V2Document.owner_id == user.id)
            .where(V2Document.is_demo.is_(True))  # type: ignore[union-attr]
        ).all()
    )

    created_any = False
    for seed in iter_demo_seed_catalog():
        if seed["title"] in existing_titles:
            continue
        document = V2Document(
            owner_id=user.id,
            organization_id=None,
            visibility="private",
            title=seed["title"],
            description=seed["description"],
            human_summary=seed["human_summary"],
            ai_generated_summary=seed["ai_generated_summary"],
            collaborators=list(seed["collaborators"]),
            main_body=list(seed["main_body"]),
            details_file_name=seed["details_file_name"],
            details_markdown_sections=list(seed["details_markdown_sections"]),
            is_demo=True,
            created_at=seed["created_at"],
            updated_at=seed["updated_at"],
        )
        refresh_v2_document_token_counts(document)
        session.add(document)
        existing_titles.add(seed["title"])
        created_any = True
    return created_any
