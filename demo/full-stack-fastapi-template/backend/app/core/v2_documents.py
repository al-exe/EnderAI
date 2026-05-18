from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, col, select

from app.models import (
    User,
    V2Document,
    V2DocumentPublic,
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
            "Customer-impact investigation with a verified operator fix and "
            "command evidence."
        ),
        "created_at": _dt(2026, 5, 10),
        "updated_at": _dt(2026, 5, 12),
        "collaborators": ["Alex Lee", "Nia Patel"],
        "ai_generated_summary": (
            "XYZ Corp traffic hit stale bridge routes after a bridge-controller "
            "deploy. The recovery path was validated by refreshing the tenant "
            "bridge mapping and confirming post-refresh health checks."
        ),
        "human_summary": (
            "XYZ Corp users hit stale bridge routing after a deploy; the "
            "validated fix is Alex's bridge refresh script."
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
                        "text": ". The incident showed up as intermittent requests "
                        "crossing old tenant bridge routes rather than the "
                        "refreshed bridge mapping."
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
                        "text": ". The useful operational record is the sequence "
                        "of logs, script execution, and health checks captured "
                        "in Details."
                    },
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
                        "---",
                        "",
                        "# Latest Stale Network Bridge Issue",
                        "",
                        "## Purpose",
                        "",
                        "Capture the full investigation record for the stale "
                        "bridge routing incident so another agent can understand "
                        "the customer impact, reproduce the checks, and apply "
                        "the known fix path without relying on chat history.",
                        "",
                        "## Executive Context",
                        "",
                        "A bridge-controller deploy left XYZ Corp traffic "
                        "reading stale tenant bridge routes. The immediate "
                        "remediation was to refresh the tenant bridge mapping "
                        "and verify the post-refresh probes.",
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
                        "crossing stale network bridge routes immediately after "
                        "the bridge-controller deploy.",
                        "",
                        "Observed pattern:",
                        "",
                        "- tenant: `xyz`",
                        "- symptom: requests occasionally used old bridge mappings",
                        "- timing: began immediately after the bridge-controller rollout",
                        "- user impact: intermittent routing failures for XYZ Corp users",
                        "",
                        "Primary checks:",
                        "",
                        "```bash",
                        "kubectl logs deploy/bridge-controller",
                        "kubectl get bridge-routes --tenant xyz",
                        "```",
                        "",
                        "The route table inspection confirmed that the tenant "
                        "mapping had not refreshed to the expected post-deploy "
                        "bridge target.",
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
                        "The fix path was to run Alex's tenant bridge refresh "
                        "script, then verify bridge health with post-refresh "
                        "probes.",
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
                        "",
                        "Verification:",
                        "",
                        "- route table changed to the expected bridge target",
                        "- post-refresh health probes passed",
                        "- no additional stale-route reports arrived for XYZ "
                        "Corp after the refresh",
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
                        "./infra/network/bridge-refresh.sh --tenant xyz",
                        "./ops/probes/bridge-health --tenant xyz",
                        "```",
                        "",
                        "## Open Follow-Up",
                        "",
                        "- Add a bridge-controller post-deploy check that "
                        "detects stale tenant route mappings before users "
                        "report symptoms.",
                        "- Add the tenant refresh command to the operator "
                        "quick-reference runbook.",
                    ]
                ),
            },
        ],
    },
    {
        "title": "V2 Document Evidence Contract",
        "description": (
            "Design note for Summary claims backed by source anchors in Details."
        ),
        "created_at": _dt(2026, 5, 13),
        "updated_at": _dt(2026, 5, 14),
        "collaborators": ["Alex Lee", "Jordan Kim"],
        "ai_generated_summary": (
            "The V2 document model should keep executive summaries short while "
            "making each claim traceable to a Details section or another "
            "source document."
        ),
        "human_summary": (
            "Human summaries should stay short, but each claim needs a direct "
            "path to detailed evidence."
        ),
        "main_body": [
            {
                "segments": [
                    {
                        "text": (
                            "The Summary view should tell a short story first: "
                            "what happened, why it matters, and what changed. "
                        )
                    },
                    {
                        "text": "It should stay succinct and executive-oriented",
                        "evidence_anchor_id": "summary-shape",
                    },
                    {
                        "text": (
                            " so a reader can understand the outcome without "
                            "reading the full working log."
                        )
                    },
                ]
            },
            {
                "segments": [
                    {"text": "The detail should still be verifiable. "},
                    {
                        "text": (
                            "Each important Summary claim needs a direct path "
                            "to supporting evidence"
                        ),
                        "evidence_anchor_id": "claim-evidence",
                    },
                    {
                        "text": (
                            ", whether that evidence lives in Details or "
                            "another linked document."
                        )
                    },
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
                        "---",
                        "",
                        "# V2 Document Evidence Contract",
                        "",
                        "## Purpose",
                        "",
                        "Define how Taskforce V2 documents should preserve a "
                        "concise human Summary while retaining enough Details "
                        "for an AI agent to reconstruct the work.",
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
                        "executive-oriented. It should capture intent, outcome, "
                        "and high-level points without exposing the full "
                        "capture log by default.",
                        "",
                        "The Summary should answer:",
                        "",
                        "- what happened",
                        "- why it mattered",
                        "- what changed",
                        "- what the next reader should do",
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
                        "- clicking a Summary claim switches to Details and "
                        "highlights the matching markdown section",
                        "- the Details content remains valid markdown when "
                        "concatenated",
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
                        "```",
                    ]
                ),
            },
        ],
    },
    {
        "title": "Hosted MCP Credential Setup Refresh",
        "description": (
            "Setup guidance for connecting an AI client with file-backed "
            "token persistence."
        ),
        "created_at": _dt(2026, 5, 15),
        "updated_at": _dt(2026, 5, 17),
        "collaborators": ["Alex Lee"],
        "ai_generated_summary": (
            "The hosted MCP setup now emphasizes file-backed token persistence, "
            "fresh-terminal reconnect steps, and a V2-specific document "
            "instruction set for V2-enabled users."
        ),
        "human_summary": (
            "Fresh terminals prevent stale MCP credentials from persisting "
            "after token creation or rotation."
        ),
        "main_body": [
            {
                "segments": [
                    {
                        "text": (
                            "The credential setup flow was refreshed because "
                            "token rotation can leave old environment values "
                            "in already-open shells. "
                        )
                    },
                    {
                        "text": (
                            "Starting from a fresh terminal prevents stale "
                            "MCP credentials from persisting"
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
                            "For V2-enabled users, the setup instructions now "
                            "push agents toward Taskforce documents instead "
                            "of legacy cases. "
                        )
                    },
                    {
                        "text": (
                            "Those users should receive document creation, "
                            "update, and finalize instructions"
                        ),
                        "evidence_anchor_id": "v2-instructions",
                    },
                    {
                        "text": (
                            " so meaningful work is captured as a Summary "
                            "backed by Details."
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
                        "---",
                        "",
                        "# Hosted MCP Credential Setup Refresh",
                        "",
                        "## Purpose",
                        "",
                        "Capture the setup behavior and V2 instruction updates "
                        "for hosted MCP credentials so future agents know how "
                        "credentials should be created, rotated, and "
                        "documented.",
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
                        "The setup flow tells users to start from a fresh "
                        "terminal after creating or rotating an MCP credential "
                        "so the shell reloads `ENDERAI_MCP_TOKEN` from "
                        "`~/.enderai_mcp_token`.",
                        "",
                        "Reason:",
                        "",
                        "- existing shells may keep the previous token in memory",
                        "- file-backed token persistence only helps after the "
                        "shell reloads the environment",
                        "- reconnecting the AI client from a fresh terminal "
                        "avoids stale credential handshakes",
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
                        "V2-enabled users receive instructions to prefer the "
                        "Taskforce V2 document toolset, create a document at "
                        "the start of meaningful work, and maintain Summary "
                        "and Details document views.",
                        "",
                        "Expected agent behavior:",
                        "",
                        "- create a Taskforce document at the start of meaningful work",
                        "- update the document as files, links, commands, "
                        "decisions, and outcomes develop",
                        "- keep the Summary concise and useful for a human reader",
                        "- keep Details as a markdown context file that an AI "
                        "agent can ingest later",
                        "- finalize the document when the work completes or stops",
                    ]
                ),
            },
        ],
    },
]


def build_v2_document_public(document: V2Document) -> V2DocumentPublic:
    return V2DocumentPublic.model_validate(document, from_attributes=True)


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


def get_v2_document_for_owner(
    session: Session, owner_id: uuid.UUID, document_id: uuid.UUID
) -> V2Document | None:
    statement = (
        select(V2Document)
        .where(V2Document.id == document_id)
        .where(V2Document.owner_id == owner_id)
    )
    return session.exec(statement).first()


def apply_v2_document_update(document: V2Document, update: V2DocumentUpdate) -> bool:
    """Apply non-null fields of update to document. Returns True if anything changed."""
    payload = update.model_dump(mode="json", exclude_unset=True)
    if not payload:
        return False
    for field, value in payload.items():
        setattr(document, field, value)
    document.updated_at = get_datetime_utc()
    return True


def ensure_v2_documents_demo_seed(session: Session, user: User) -> bool:
    """Lazily clone the demo catalog into the user's account.

    Idempotent: if the user already has any is_demo=True v2_document rows we
    treat the seed as already applied for them. Returns True if any rows were
    created or refreshed in this call.
    """
    existing_count = session.exec(
        select(V2Document)
        .where(V2Document.owner_id == user.id)
        .where(V2Document.is_demo.is_(True))  # type: ignore[union-attr]
    ).first()
    if existing_count is not None:
        return False

    for seed in DEMO_SEED:
        document = V2Document(
            owner_id=user.id,
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
        session.add(document)
    return True
