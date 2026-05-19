import {
  createV2Document,
  listV2Documents,
  patchV2Document,
  readV2Document,
} from "./client.js";
import { decide, scoreCongruence } from "./scoring/engine.js";
import type { CongruenceScore, Decision, ScoredCandidate } from "./scoring/types.js";
import { planSelfHeal } from "./selfHeal.js";
import {
  clearActiveDocument,
  setActiveDocument,
  touchActiveDocument,
  type ActiveDocumentState,
} from "./active.js";
import type {
  MatchRequest,
  V2Document,
  V2DocumentDetailsSection,
  V2DocumentParagraph,
  V2DocumentUpdate,
} from "./types.js";

export type BeginDocumentArgs = {
  request_summary: string;
  goal?: string;
  acceptance_criteria?: string;
  title?: string;
  collaborators?: string[];
  files?: string[];
  symbols?: string[];
  errors?: string[];
  contexts?: string[];
  document_id?: string;
  reuse_within_seconds?: number;
  force_new?: boolean;
  visibility?: "private" | "organization";
  demo?: boolean;
};

export type BeginDocumentResult = {
  document_id: string;
  document_url_path: string;
  title: string;
  reused_existing: boolean;
  match_confidence: "high" | "medium" | "low" | "explicit" | "forced-new";
  match_total?: number;
  match_reasons: string[];
  candidate_summaries: Array<{
    document_id: string;
    title: string;
    total: number;
    band: string;
    weak_signals: string[];
    conflicts: string[];
  }>;
  self_healed_fields: string[];
  agent_usage_note: string;
};

export type UpdateDocumentArgs = {
  document_id?: string;
  title?: string;
  description?: string;
  human_summary?: string;
  summary_points?: string[];
  ai_generated_summary?: string;
  collaborators?: string[];
  details_sections?: Array<{ anchor_id: string; markdown: string }>;
  commands?: Array<{ cmd: string; purpose?: string; salient_result?: string; ts?: string }>;
  files?: string[];
  links?: string[];
  decisions?: Array<{ statement: string; rationale?: string }>;
  changes?: Array<{ kind: string; summary: string; files?: string[] }>;
  open_questions?: string[];
  progress_note?: string;
  visibility?: "private" | "organization";
  demo?: boolean;
};

export type UpdateDocumentResult = {
  document_id: string;
  title: string;
  document_url_path: string;
  patched_fields: string[];
  agent_usage_note: string;
};

export type FinishDocumentArgs = {
  document_id?: string;
  outcome?: string;
  validation?: string[];
  follow_ups?: string[];
  status?: "done" | "paused" | "blocked" | "superseded";
  closing_note?: string;
  demo?: boolean;
};

export type FinishDocumentResult = {
  document_id: string;
  title: string;
  document_url_path: string;
  status: string;
  agent_usage_note: string;
};

const DEFAULT_TITLE = "Untitled work";

function normalizeRequest(args: BeginDocumentArgs): MatchRequest {
  return {
    request_summary: args.request_summary,
    title: args.title?.trim() || undefined,
    goal: args.goal?.trim() || undefined,
    acceptance_criteria: args.acceptance_criteria?.trim() || undefined,
    collaborators: dedupeStrings(args.collaborators),
    files: dedupeStrings(args.files),
    symbols: dedupeStrings(args.symbols),
    errors: dedupeStrings(args.errors),
    contexts: dedupeStrings(args.contexts),
    reuse_within_seconds: args.reuse_within_seconds,
    force_new: args.force_new,
    document_id: args.document_id,
    visibility: args.visibility,
    demo: args.demo,
  };
}

function dedupeStrings(values: string[] | undefined): string[] {
  if (!values) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const v of values) {
    const trimmed = v.trim();
    if (!trimmed) continue;
    const key = trimmed.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(trimmed);
  }
  return out;
}

function documentUrlPath(documentId: string): string {
  return `/v2/library/${documentId}`;
}

function summarizeCandidates(scored: ScoredCandidate[]): BeginDocumentResult["candidate_summaries"] {
  return scored.slice(0, 5).map((s) => ({
    document_id: s.candidate.id,
    title: s.candidate.title,
    total: s.score.total,
    band: s.score.band,
    weak_signals: s.score.weakSignals,
    conflicts: s.score.conflicts.map((c) => c.name),
  }));
}

function reasonsFromScore(score: CongruenceScore): string[] {
  const positives = score.signals
    .filter((s) => s.kind === "positive" && s.strength > 0)
    .sort((a, b) => b.contribution - a.contribution)
    .slice(0, 4)
    .map((s) => s.reason);
  const conflicts = score.conflicts.map((s) => `conflict: ${s.reason}`);
  return [...positives, ...conflicts];
}

function deriveTitle(args: BeginDocumentArgs): string {
  if (args.title?.trim()) return args.title.trim();
  const summary = args.request_summary.trim();
  if (!summary) return DEFAULT_TITLE;
  const firstLine = summary.split(/[\n.!?]/)[0].trim();
  return firstLine.slice(0, 80) || DEFAULT_TITLE;
}

function initialDocumentBody(args: BeginDocumentArgs): {
  main_body: V2DocumentParagraph[];
  details_markdown_sections: V2DocumentDetailsSection[];
  details_file_name: string;
} {
  const title = deriveTitle(args);
  const detailsLines: string[] = [
    "<!-- evidence-anchor: request -->",
    "## Request",
    "",
    args.request_summary.trim(),
    "",
  ];
  if (args.goal?.trim()) {
    detailsLines.push(`**Goal:** ${args.goal.trim()}`);
    detailsLines.push("");
  }
  if (args.acceptance_criteria?.trim()) {
    detailsLines.push(`**Acceptance criteria:** ${args.acceptance_criteria.trim()}`);
    detailsLines.push("");
  }
  const fileList = dedupeStrings(args.files);
  const symbolList = dedupeStrings(args.symbols);
  const errorList = dedupeStrings(args.errors);
  const contextList = dedupeStrings(args.contexts);
  if (fileList.length) {
    detailsLines.push("**Files in scope:**", "");
    for (const f of fileList) detailsLines.push(`- \`${f}\``);
    detailsLines.push("");
  }
  if (symbolList.length) {
    detailsLines.push("**Symbols:**", "");
    for (const s of symbolList) detailsLines.push(`- \`${s}\``);
    detailsLines.push("");
  }
  if (errorList.length) {
    detailsLines.push("**Errors:**", "");
    for (const e of errorList) detailsLines.push(`- ${e}`);
    detailsLines.push("");
  }
  if (contextList.length) {
    detailsLines.push("**Context:**", "");
    for (const c of contextList) detailsLines.push(`- ${c}`);
    detailsLines.push("");
  }
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64) || "document";
  return {
    main_body: [
      {
        segments: [
          {
            text: `Active request: ${args.request_summary.trim()}`,
            evidence_anchor_id: "request",
          },
        ],
      },
    ],
    details_markdown_sections: [
      { anchor_id: "request", markdown: detailsLines.join("\n").trimEnd() },
    ],
    details_file_name: `${slug}.details.md`,
  };
}

export type ToolEnv = {
  bearerToken?: string;
  state: ActiveDocumentState;
};

export async function beginDocument(
  args: BeginDocumentArgs,
  env: ToolEnv,
): Promise<BeginDocumentResult> {
  const request = normalizeRequest(args);
  const fetchArgs = { bearerToken: env.bearerToken, demo: args.demo };
  const baseTitle = deriveTitle(args);

  // 1. Explicit document_id wins.
  if (request.document_id) {
    const doc = await readV2Document(request.document_id, fetchArgs);
    const heal = planSelfHeal({ document: doc, request });
    let working = doc;
    if (Object.keys(heal.patch).length > 0) {
      working = await patchV2Document(doc.id, heal.patch, fetchArgs);
    }
    setActiveDocument(env.state, {
      documentId: working.id,
      title: working.title,
      demo: args.demo,
    });
    return {
      document_id: working.id,
      document_url_path: documentUrlPath(working.id),
      title: working.title,
      reused_existing: true,
      match_confidence: "explicit",
      match_reasons: [`Reused document ${working.id} by explicit document_id`],
      candidate_summaries: [],
      self_healed_fields: heal.appliedFixes,
      agent_usage_note: agentUsageNote("reuse", working.title),
    };
  }

  // 2. force_new → straight create.
  if (request.force_new) {
    const created = await createV2Document(
      {
        title: baseTitle,
        description: args.goal?.trim() || args.request_summary.trim().slice(0, 280),
        ai_generated_summary: `Agent-maintained summary. Active request: ${args.request_summary.trim()}`.slice(0, 600),
        collaborators: request.collaborators,
        visibility: request.visibility,
        ...initialDocumentBody(args),
      },
      fetchArgs,
    );
    setActiveDocument(env.state, {
      documentId: created.id,
      title: created.title,
      demo: args.demo,
    });
    return {
      document_id: created.id,
      document_url_path: documentUrlPath(created.id),
      title: created.title,
      reused_existing: false,
      match_confidence: "forced-new",
      match_reasons: ["force_new=true; created fresh document"],
      candidate_summaries: [],
      self_healed_fields: [],
      agent_usage_note: agentUsageNote("create", created.title),
    };
  }

  // 3. List + score + decide.
  const list = await listV2Documents(fetchArgs);
  const decision: Decision = decide({
    candidates: list.data,
    request,
  });

  if (decision.action === "reuse" && decision.documentId && decision.score) {
    const doc = await readV2Document(decision.documentId, fetchArgs);
    const heal = planSelfHeal({ document: doc, request, score: decision.score });
    let working = doc;
    if (Object.keys(heal.patch).length > 0) {
      working = await patchV2Document(doc.id, heal.patch, fetchArgs);
    }
    setActiveDocument(env.state, {
      documentId: working.id,
      title: working.title,
      demo: args.demo,
    });
    return {
      document_id: working.id,
      document_url_path: documentUrlPath(working.id),
      title: working.title,
      reused_existing: true,
      match_confidence: decision.score.band,
      match_total: decision.score.total,
      match_reasons: [decision.reason, ...reasonsFromScore(decision.score)],
      candidate_summaries: summarizeCandidates(decision.candidates),
      self_healed_fields: heal.appliedFixes,
      agent_usage_note: agentUsageNote("reuse", working.title),
    };
  }

  // create path
  const created = await createV2Document(
    {
      title: baseTitle,
      description: args.goal?.trim() || args.request_summary.trim().slice(0, 280),
      ai_generated_summary: `Agent-maintained summary. Active request: ${args.request_summary.trim()}`.slice(0, 600),
      collaborators: request.collaborators,
      visibility: request.visibility,
      ...initialDocumentBody(args),
    },
    fetchArgs,
  );
  setActiveDocument(env.state, {
    documentId: created.id,
    title: created.title,
    demo: args.demo,
  });
  const matchConfidence: BeginDocumentResult["match_confidence"] =
    decision.candidates.length === 0 ? "low" : decision.score?.band ?? "low";
  return {
    document_id: created.id,
    document_url_path: documentUrlPath(created.id),
    title: created.title,
    reused_existing: false,
    match_confidence: matchConfidence,
    match_total: decision.score?.total,
    match_reasons: [decision.reason],
    candidate_summaries: summarizeCandidates(decision.candidates),
    self_healed_fields: [],
    agent_usage_note: agentUsageNote("create", created.title),
  };
}

// --- update -----------------------------------------------------------------

function isoNow(): string {
  return new Date().toISOString();
}

function upsertDetailsSection(
  sections: V2DocumentDetailsSection[],
  anchorId: string,
  markdown: string,
): V2DocumentDetailsSection[] {
  const idx = sections.findIndex((s) => s.anchor_id === anchorId);
  if (idx === -1) {
    return [...sections, { anchor_id: anchorId, markdown }];
  }
  const next = sections.slice();
  next[idx] = { anchor_id: anchorId, markdown };
  return next;
}

function appendWorkingLogSection(
  sections: V2DocumentDetailsSection[],
  args: UpdateDocumentArgs,
): V2DocumentDetailsSection[] {
  const lines: string[] = [];
  const ts = isoNow();
  lines.push(`<!-- evidence-anchor: working-log-${ts} -->`);
  lines.push(`## Working Log — ${ts}`);
  lines.push("");
  if (args.progress_note?.trim()) {
    lines.push(args.progress_note.trim());
    lines.push("");
  }
  if (args.commands?.length) {
    lines.push("**Commands:**", "");
    for (const c of args.commands) {
      lines.push(`- \`${c.cmd}\`${c.purpose ? ` — ${c.purpose}` : ""}${c.salient_result ? ` → ${c.salient_result}` : ""}`);
    }
    lines.push("");
  }
  if (args.files?.length) {
    lines.push("**Files touched:**", "");
    for (const f of args.files) lines.push(`- \`${f}\``);
    lines.push("");
  }
  if (args.links?.length) {
    lines.push("**Links:**", "");
    for (const l of args.links) lines.push(`- ${l}`);
    lines.push("");
  }
  if (args.decisions?.length) {
    lines.push("**Decisions:**", "");
    for (const d of args.decisions) {
      lines.push(`- ${d.statement}${d.rationale ? ` — ${d.rationale}` : ""}`);
    }
    lines.push("");
  }
  if (args.changes?.length) {
    lines.push("**Changes:**", "");
    for (const ch of args.changes) {
      lines.push(`- (${ch.kind}) ${ch.summary}${ch.files?.length ? ` — ${ch.files.map((f) => `\`${f}\``).join(", ")}` : ""}`);
    }
    lines.push("");
  }
  if (args.open_questions?.length) {
    lines.push("**Open questions:**", "");
    for (const q of args.open_questions) lines.push(`- ${q}`);
    lines.push("");
  }
  if (lines.length <= 3) return sections; // nothing material to log
  const anchor = `working-log-${ts.replace(/[^0-9]/g, "")}`;
  return upsertDetailsSection(sections, anchor, lines.join("\n").trimEnd());
}

export async function updateDocument(
  args: UpdateDocumentArgs,
  env: ToolEnv,
): Promise<UpdateDocumentResult> {
  const documentId = args.document_id ?? env.state.documentId;
  if (!documentId) {
    throw new Error(
      "enderai_update_document requires an active document. Run enderai_begin_document first or pass document_id.",
    );
  }
  const fetchArgs = { bearerToken: env.bearerToken, demo: args.demo ?? env.state.demo };
  const doc = await readV2Document(documentId, fetchArgs);
  const patch: V2DocumentUpdate = {};
  const patched: string[] = [];

  if (args.title?.trim() && args.title.trim() !== doc.title) {
    patch.title = args.title.trim();
    patched.push("title");
  }
  if (args.description !== undefined && args.description.trim() !== doc.description) {
    patch.description = args.description.trim();
    patched.push("description");
  }
  if (args.human_summary !== undefined) {
    // Only patch human_summary when the caller explicitly sets it. The plan
    // calls out that human_summary is human-owned by default.
    patch.human_summary = args.human_summary;
    patched.push("human_summary");
  }
  if (args.ai_generated_summary !== undefined) {
    patch.ai_generated_summary = args.ai_generated_summary;
    patched.push("ai_generated_summary");
  }
  if (args.collaborators?.length) {
    const merged = dedupeStrings([...doc.collaborators, ...args.collaborators]);
    if (merged.length !== doc.collaborators.length) {
      patch.collaborators = merged;
      patched.push("collaborators");
    }
  }
  if (args.visibility !== undefined && args.visibility !== doc.visibility) {
    patch.visibility = args.visibility;
    patched.push("visibility");
  }

  let body = doc.main_body;
  let sections = doc.details_markdown_sections;

  if (args.details_sections?.length) {
    for (const section of args.details_sections) {
      sections = upsertDetailsSection(sections, section.anchor_id, section.markdown);
    }
    patched.push("details_markdown_sections (explicit upserts)");
  }

  const hasWorkingLogPayload = Boolean(
    args.progress_note?.trim() ||
      args.commands?.length ||
      args.files?.length ||
      args.links?.length ||
      args.decisions?.length ||
      args.changes?.length ||
      args.open_questions?.length,
  );
  if (hasWorkingLogPayload) {
    sections = appendWorkingLogSection(sections, args);
    if (!patched.includes("details_markdown_sections (working log)")) {
      patched.push("details_markdown_sections (working log)");
    }
  }

  if (args.summary_points?.length) {
    const existing = new Set(
      body.flatMap((p) => p.segments.map((s) => s.text.trim().toLowerCase())),
    );
    const additions = args.summary_points
      .map((p) => p.trim())
      .filter((p) => p && !existing.has(p.toLowerCase()));
    if (additions.length > 0) {
      body = [
        ...body,
        ...additions.map((text) => ({ segments: [{ text }] })),
      ];
      patch.main_body = body;
      patched.push("main_body (summary points)");
    }
  }

  if (sections !== doc.details_markdown_sections) {
    patch.details_markdown_sections = sections;
  }

  if (Object.keys(patch).length === 0) {
    throw new Error(
      "enderai_update_document was called with no changes; pass at least one of: summary_points, details_sections, progress_note, commands, files, links, decisions, changes, open_questions, or a top-level field.",
    );
  }

  const next = await patchV2Document(documentId, patch, fetchArgs);
  touchActiveDocument(env.state);
  return {
    document_id: next.id,
    title: next.title,
    document_url_path: documentUrlPath(next.id),
    patched_fields: patched,
    agent_usage_note: agentUsageNote("update", next.title),
  };
}

// --- finish -----------------------------------------------------------------

export async function finishDocument(
  args: FinishDocumentArgs,
  env: ToolEnv,
): Promise<FinishDocumentResult> {
  const documentId = args.document_id ?? env.state.documentId;
  if (!documentId) {
    throw new Error(
      "enderai_finish_document requires an active document. Run enderai_begin_document first or pass document_id.",
    );
  }
  const fetchArgs = { bearerToken: env.bearerToken, demo: args.demo ?? env.state.demo };
  const doc = await readV2Document(documentId, fetchArgs);
  const lines: string[] = [];
  lines.push("<!-- evidence-anchor: outcome -->");
  lines.push("## Outcome");
  lines.push("");
  lines.push(`status: ${args.status ?? "done"}`);
  lines.push("");
  if (args.outcome?.trim()) {
    lines.push(args.outcome.trim());
    lines.push("");
  }
  if (args.validation?.length) {
    lines.push("**Validation:**", "");
    for (const v of args.validation) lines.push(`- ${v}`);
    lines.push("");
  }
  if (args.follow_ups?.length) {
    lines.push("**Follow-ups:**", "");
    for (const f of args.follow_ups) lines.push(`- ${f}`);
    lines.push("");
  }
  if (args.closing_note?.trim()) {
    lines.push(args.closing_note.trim());
    lines.push("");
  }

  const nextSections = upsertDetailsSection(
    doc.details_markdown_sections,
    "outcome",
    lines.join("\n").trimEnd(),
  );

  const summaryAddition = args.outcome?.trim()
    ? `Outcome: ${args.outcome.trim()}`
    : `Marked ${args.status ?? "done"}.`;
  const existingSummaryTexts = new Set(
    doc.main_body.flatMap((p) => p.segments.map((s) => s.text.trim().toLowerCase())),
  );
  const summaryPatch = existingSummaryTexts.has(summaryAddition.toLowerCase())
    ? doc.main_body
    : [
        ...doc.main_body,
        {
          segments: [
            { text: summaryAddition, evidence_anchor_id: "outcome" },
          ],
        },
      ];

  const next = await patchV2Document(
    documentId,
    {
      details_markdown_sections: nextSections,
      main_body: summaryPatch,
    },
    fetchArgs,
  );
  clearActiveDocument(env.state);
  return {
    document_id: next.id,
    title: next.title,
    document_url_path: documentUrlPath(next.id),
    status: args.status ?? "done",
    agent_usage_note: `Finalized "${next.title}". Re-run enderai_begin_document for the next unit of work.`,
  };
}

function agentUsageNote(kind: "create" | "reuse" | "update", title: string): string {
  switch (kind) {
    case "create":
      return `Created Taskforce v2 document "${title}". Use enderai_update_document as findings, commands, files, and decisions develop. Keep Summary claims backed by Details evidence anchors. Run enderai_finish_document when the work completes or pauses.`;
    case "reuse":
      return `Reusing Taskforce v2 document "${title}". Use enderai_update_document to add new evidence, decisions, and commands. Keep Summary claims backed by Details evidence anchors. Run enderai_finish_document when the work completes or pauses.`;
    case "update":
      return `Updated Taskforce v2 document "${title}". Keep going with enderai_update_document as material progress develops, or run enderai_finish_document when the work completes or pauses.`;
  }
}

// Re-exports used by mcpServer and tests.
export type { V2Document, V2DocumentUpdate, MatchRequest } from "./types.js";
export { planSelfHeal } from "./selfHeal.js";
export { scoreCongruence, decide } from "./scoring/engine.js";
