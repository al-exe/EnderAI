import type {
  V2Document,
  V2DocumentDetailsSection,
  V2DocumentParagraph,
  V2DocumentUpdate,
  MatchRequest,
} from "./types.js";
import type { CongruenceScore, SignalName } from "./scoring/types.js";

export type SelfHealResult = {
  patch: V2DocumentUpdate;
  appliedFixes: string[];
};

function nonEmpty<T>(value: T | undefined | null): value is T {
  return value !== undefined && value !== null;
}

function uniq(values: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const v of values) {
    const trimmed = v.trim();
    if (!trimmed || seen.has(trimmed.toLowerCase())) continue;
    seen.add(trimmed.toLowerCase());
    out.push(trimmed);
  }
  return out;
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

function fileBaseName(title: string): string {
  const slug = slugify(title) || "document";
  return `${slug}.details.md`;
}

function ensureAnchorIds(sections: V2DocumentDetailsSection[]): {
  sections: V2DocumentDetailsSection[];
  changed: boolean;
} {
  const seen = new Set<string>();
  let changed = false;
  const next = sections.map((section, idx) => {
    let id = section.anchor_id?.trim();
    if (!id) {
      id = `section-${idx + 1}`;
      changed = true;
    }
    while (seen.has(id)) {
      changed = true;
      id = `${id}-${idx + 1}`;
    }
    seen.add(id);
    if (id === section.anchor_id) return section;
    changed = true;
    return { ...section, anchor_id: id };
  });
  return { sections: next, changed };
}

function buildCurrentWorkMarkdown(request: MatchRequest, weakSignals: SignalName[]): string {
  const lines: string[] = ["<!-- evidence-anchor: current-work -->", "## Current Work", ""];
  lines.push(request.request_summary);
  lines.push("");
  if (request.goal) {
    lines.push(`**Goal:** ${request.goal}`);
    lines.push("");
  }
  if (request.acceptance_criteria) {
    lines.push(`**Acceptance criteria:** ${request.acceptance_criteria}`);
    lines.push("");
  }
  const includeFiles = request.files.length > 0 && weakSignals.includes("file-overlap");
  const includeSymbols = request.symbols.length > 0 && weakSignals.includes("symbol-overlap");
  const includeErrors = request.errors.length > 0 && weakSignals.includes("error-overlap");
  const includeContexts = request.contexts.length > 0;

  if (includeFiles) {
    lines.push("**Files in scope:**");
    lines.push("");
    for (const f of request.files) lines.push(`- \`${f}\``);
    lines.push("");
  }
  if (includeSymbols) {
    lines.push("**Symbols:**");
    lines.push("");
    for (const s of request.symbols) lines.push(`- \`${s}\``);
    lines.push("");
  }
  if (includeErrors) {
    lines.push("**Errors:**");
    lines.push("");
    for (const e of request.errors) lines.push(`- ${e}`);
    lines.push("");
  }
  if (includeContexts) {
    lines.push("**Context:**");
    lines.push("");
    for (const c of request.contexts) lines.push(`- ${c}`);
    lines.push("");
  }
  return lines.join("\n").trimEnd();
}

function summaryParagraphFor(request: MatchRequest): V2DocumentParagraph {
  const text = `New work added: ${request.request_summary.trim()}`;
  return { segments: [{ text }] };
}

export type SelfHealArgs = {
  document: V2Document;
  request: MatchRequest;
  score?: CongruenceScore;
};

/**
 * Plan a minimal PATCH that:
 *   - fills missing description / ai_generated_summary / details file name
 *   - generates anchor IDs for Details sections missing them
 *   - merges new collaborators
 *   - adds a "Current Work" Details section seeded from the new request,
 *     scoped to which signals were weak (so we don't dump irrelevant content)
 *
 * The plan never overwrites human_summary, and only touches title when
 * `request.title` is provided and differs from the current title meaningfully.
 */
export function planSelfHeal(args: SelfHealArgs): SelfHealResult {
  const { document, request } = args;
  const weakSignals = args.score?.weakSignals ?? [];
  const patch: V2DocumentUpdate = {};
  const fixes: string[] = [];

  if (!document.description.trim()) {
    const stub = request.goal ?? request.request_summary;
    if (stub.trim()) {
      patch.description = stub.trim().slice(0, 280);
      fixes.push("populated missing description");
    }
  }

  if (!document.ai_generated_summary.trim()) {
    patch.ai_generated_summary =
      `Agent-maintained summary. Active request: ${request.request_summary.trim()}`.slice(0, 600);
    fixes.push("populated missing ai_generated_summary");
  }

  if (!document.details_file_name.trim()) {
    patch.details_file_name = fileBaseName(document.title);
    fixes.push(`set Details file name to ${patch.details_file_name}`);
  }

  const mergedCollaborators = uniq([
    ...document.collaborators,
    ...request.collaborators,
  ]);
  if (mergedCollaborators.length !== document.collaborators.length) {
    patch.collaborators = mergedCollaborators;
    const added = mergedCollaborators
      .filter((c) => !document.collaborators.some((d) => d.toLowerCase() === c.toLowerCase()))
      .filter(nonEmpty);
    if (added.length > 0) fixes.push(`merged collaborators: ${added.join(", ")}`);
  }

  let workingSections = document.details_markdown_sections.map((s) => ({ ...s }));
  const { sections: normalized, changed: anchorsChanged } = ensureAnchorIds(workingSections);
  if (anchorsChanged) {
    workingSections = normalized;
    fixes.push("normalized Details anchor IDs");
  }

  // Repair Summary segments whose evidence_anchor_id no longer points anywhere.
  const validAnchors = new Set(workingSections.map((s) => s.anchor_id));
  let bodyChanged = false;
  const repairedBody = document.main_body.map((paragraph) => ({
    segments: paragraph.segments.map((segment) => {
      if (
        segment.evidence_anchor_id &&
        !validAnchors.has(segment.evidence_anchor_id)
      ) {
        bodyChanged = true;
        return { text: segment.text };
      }
      return segment;
    }),
  }));
  if (bodyChanged) {
    fixes.push("dropped Summary anchors pointing at missing Details sections");
  }

  // Add a Current Work section when reuse was decided and at least one
  // request-side signal didn't already match the doc. This is the recipe
  // mentioned in the plan: weak signals are the gaps we fill.
  const fillableSignals: SignalName[] = [
    "file-overlap",
    "symbol-overlap",
    "error-overlap",
    "anchor-overlap",
  ];
  const hasContentGap = weakSignals.some((s) => fillableSignals.includes(s));
  const hasNewRequestContent =
    request.request_summary.trim().length > 0 ||
    request.files.length > 0 ||
    request.symbols.length > 0 ||
    request.errors.length > 0 ||
    request.contexts.length > 0;
  if (hasContentGap && hasNewRequestContent) {
    const newSection: V2DocumentDetailsSection = {
      anchor_id: `current-work-${Date.now().toString(36)}`,
      markdown: buildCurrentWorkMarkdown(request, weakSignals),
    };
    workingSections = [...workingSections, newSection];
    fixes.push(`added Current Work Details section (${newSection.anchor_id})`);

    const summaryAddition = summaryParagraphFor(request);
    const repairedBodyWithAddition = [...repairedBody, summaryAddition];
    patch.main_body = repairedBodyWithAddition;
    bodyChanged = true;
  } else if (bodyChanged) {
    patch.main_body = repairedBody;
  }

  if (
    anchorsChanged ||
    (hasContentGap && hasNewRequestContent)
  ) {
    patch.details_markdown_sections = workingSections;
  }

  // Optional title repair: only when caller passed a new title that meaningfully
  // differs, and never on its own (would be too aggressive).
  if (request.title && request.title.trim() && request.title.trim() !== document.title) {
    // Don't change title unless the doc is otherwise being substantially
    // updated — title rewrites are too destructive to do as a silent heal.
    if (Object.keys(patch).length > 0) {
      patch.title = request.title.trim();
      fixes.push(`updated title to "${patch.title}"`);
    }
  }

  return { patch, appliedFixes: fixes };
}
