import type { V2Document, V2DocumentParagraph, V2DocumentDetailsSection, MatchRequest } from "../types.js";
import type { SignalResult, SignalScorer } from "./types.js";

const STOPWORDS = new Set([
  "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
  "with", "by", "is", "are", "was", "were", "be", "been", "being",
  "this", "that", "these", "those", "it", "its", "as", "at", "from",
]);

export function tokenize(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .toLowerCase()
    .replace(/[^\p{L}\p{N}_./-]+/gu, " ")
    .split(/\s+/)
    .filter((token) => token.length > 1 && !STOPWORDS.has(token));
}

function tokenSet(value: string | undefined): Set<string> {
  return new Set(tokenize(value));
}

function jaccard(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0;
  let intersect = 0;
  for (const t of a) if (b.has(t)) intersect += 1;
  const union = a.size + b.size - intersect;
  if (union === 0) return 0;
  return intersect / union;
}

function flattenBodyText(paragraphs: V2DocumentParagraph[]): string {
  return paragraphs
    .map((p) => p.segments.map((s) => s.text).join(""))
    .join("\n");
}

function flattenDetailsText(sections: V2DocumentDetailsSection[]): string {
  return sections.map((s) => s.markdown).join("\n");
}

function docCorpus(doc: V2Document): string {
  return [
    doc.title,
    doc.description,
    doc.human_summary,
    doc.ai_generated_summary,
    flattenBodyText(doc.main_body),
    flattenDetailsText(doc.details_markdown_sections),
  ].join("\n");
}

function ratio(matched: number, requested: number): number {
  if (requested === 0) return 0;
  return Math.min(1, matched / requested);
}

function caseInsensitiveContains(haystack: string, needle: string): boolean {
  if (!needle) return false;
  return haystack.toLowerCase().includes(needle.toLowerCase());
}

// ----- positive signals ------------------------------------------------------

export const scoreTitleOverlap: SignalScorer = (candidate, request) => {
  const candidateTitle = candidate.title.trim().toLowerCase();
  const requestTitle = (request.title ?? "").trim().toLowerCase();
  const requestSummary = request.request_summary.trim().toLowerCase();

  if (requestTitle && candidateTitle && candidateTitle === requestTitle) {
    return {
      name: "title-overlap",
      kind: "positive",
      strength: 1,
      reason: `Exact title match: "${candidate.title}"`,
    };
  }

  const requestTokens = tokenSet(request.title ? request.title : request.request_summary);
  const candidateTokens = tokenSet(candidate.title);
  const score = jaccard(candidateTokens, requestTokens);
  const matched = [...requestTokens].filter((t) => candidateTokens.has(t)).slice(0, 6);

  return {
    name: "title-overlap",
    kind: "positive",
    strength: score,
    reason:
      matched.length > 0
        ? `Title tokens overlap on ${matched.map((t) => `'${t}'`).join(", ")}`
        : `No title token overlap with request`,
    evidence: { matched, jaccard: score, source: requestTitle ? "title" : "request_summary" },
  };
};

export const scoreFileOverlap: SignalScorer = (candidate, request) => {
  if (request.files.length === 0) {
    return {
      name: "file-overlap",
      kind: "positive",
      strength: 0,
      reason: "Request listed no files",
    };
  }
  const corpus = docCorpus(candidate).toLowerCase();
  const matched: string[] = [];
  for (const file of request.files) {
    const normalized = file.trim().toLowerCase();
    if (!normalized) continue;
    if (corpus.includes(normalized)) {
      matched.push(file);
      continue;
    }
    // Also try the basename and directory prefix as proxies.
    const parts = normalized.split("/");
    const basename = parts[parts.length - 1];
    if (basename && basename !== normalized && corpus.includes(basename)) {
      matched.push(file);
    }
  }
  const strength = ratio(matched.length, request.files.length);
  return {
    name: "file-overlap",
    kind: "positive",
    strength,
    reason:
      matched.length > 0
        ? `Doc mentions ${matched.length}/${request.files.length} request files`
        : `Doc does not mention any of the ${request.files.length} request files`,
    evidence: { matched },
  };
};

export const scoreSymbolOverlap: SignalScorer = (candidate, request) => {
  if (request.symbols.length === 0) {
    return {
      name: "symbol-overlap",
      kind: "positive",
      strength: 0,
      reason: "Request listed no symbols",
    };
  }
  const corpus = docCorpus(candidate);
  const matched = request.symbols.filter((sym) => caseInsensitiveContains(corpus, sym));
  const strength = ratio(matched.length, request.symbols.length);
  return {
    name: "symbol-overlap",
    kind: "positive",
    strength,
    reason:
      matched.length > 0
        ? `Doc mentions ${matched.length}/${request.symbols.length} request symbols`
        : `Doc does not mention request symbols`,
    evidence: { matched },
  };
};

export const scoreErrorOverlap: SignalScorer = (candidate, request) => {
  if (request.errors.length === 0) {
    return {
      name: "error-overlap",
      kind: "positive",
      strength: 0,
      reason: "Request listed no error strings",
    };
  }
  const corpus = docCorpus(candidate);
  const matched = request.errors.filter((err) => caseInsensitiveContains(corpus, err));
  const strength = ratio(matched.length, request.errors.length);
  return {
    name: "error-overlap",
    kind: "positive",
    strength,
    reason:
      matched.length > 0
        ? `Doc mentions ${matched.length}/${request.errors.length} request error strings`
        : `Doc does not mention request error strings`,
    evidence: { matched },
  };
};

function anchorTokens(value: string): Set<string> {
  return new Set(
    value
      .toLowerCase()
      .split(/[\s/_.-]+/)
      .filter((t) => t.length > 1 && !STOPWORDS.has(t)),
  );
}

export const scoreAnchorOverlap: SignalScorer = (candidate, request) => {
  if (candidate.details_markdown_sections.length === 0) {
    return {
      name: "anchor-overlap",
      kind: "positive",
      strength: 0,
      reason: "Doc has no Details anchors",
    };
  }
  const anchorIds = candidate.details_markdown_sections.map((s) =>
    s.anchor_id.toLowerCase(),
  );
  const hints = [
    ...request.files,
    ...request.symbols,
    ...request.errors,
    ...request.contexts,
    request.title ?? "",
  ]
    .map((s) => s.trim())
    .filter(Boolean);
  if (hints.length === 0) {
    return {
      name: "anchor-overlap",
      kind: "positive",
      strength: 0,
      reason: "Request has no hints to match against Details anchors",
    };
  }
  const hintTokens = new Set<string>();
  for (const h of hints) for (const t of anchorTokens(h)) hintTokens.add(t);
  const matched: string[] = [];
  for (const id of anchorIds) {
    const idTokens = anchorTokens(id);
    let hit = false;
    for (const t of idTokens) {
      if (hintTokens.has(t)) {
        hit = true;
        break;
      }
    }
    if (hit) matched.push(id);
  }
  const strength = ratio(matched.length, Math.min(anchorIds.length, Math.max(1, hints.length)));
  return {
    name: "anchor-overlap",
    kind: "positive",
    strength,
    reason:
      matched.length > 0
        ? `Hints overlap with existing anchors: ${matched.slice(0, 3).join(", ")}`
        : "Request hints do not overlap with existing Details anchors",
    evidence: { matched },
  };
};

export const scoreCollaboratorOverlap: SignalScorer = (candidate, request) => {
  if (request.collaborators.length === 0 || candidate.collaborators.length === 0) {
    return {
      name: "collaborator-overlap",
      kind: "positive",
      strength: 0,
      reason: "No collaborators to compare",
    };
  }
  const docSet = new Set(candidate.collaborators.map((c) => c.trim().toLowerCase()));
  const matched = request.collaborators.filter((c) =>
    docSet.has(c.trim().toLowerCase()),
  );
  const strength = ratio(matched.length, request.collaborators.length);
  return {
    name: "collaborator-overlap",
    kind: "positive",
    strength,
    reason:
      matched.length > 0
        ? `Shared collaborators: ${matched.join(", ")}`
        : "No shared collaborators",
    evidence: { matched },
  };
};

const DEFAULT_RECENCY_WINDOW_SECONDS = 60 * 60 * 24 * 30; // 30 days

export const scoreRecency: SignalScorer = (candidate, request) => {
  const updatedAt = candidate.updated_at ?? candidate.created_at;
  if (!updatedAt) {
    return {
      name: "recency",
      kind: "positive",
      strength: 0,
      reason: "Doc has no updated_at",
    };
  }
  const updatedMs = Date.parse(updatedAt);
  if (Number.isNaN(updatedMs)) {
    return {
      name: "recency",
      kind: "positive",
      strength: 0,
      reason: `Unparseable updated_at: ${updatedAt}`,
    };
  }
  const windowSeconds = request.reuse_within_seconds ?? DEFAULT_RECENCY_WINDOW_SECONDS;
  const ageSeconds = Math.max(0, (Date.now() - updatedMs) / 1000);
  const strength = Math.max(0, 1 - ageSeconds / windowSeconds);
  const ageDays = Math.round(ageSeconds / 86400);
  return {
    name: "recency",
    kind: "positive",
    strength,
    reason:
      strength > 0
        ? `Updated ${ageDays} day${ageDays === 1 ? "" : "s"} ago`
        : `Updated outside the ${Math.round(windowSeconds / 86400)}-day reuse window`,
    evidence: { ageSeconds, windowSeconds, updatedAt },
  };
};

const CONTINUE_PHRASES = [
  "continue",
  "continuing",
  "follow up",
  "follow-up",
  "followup",
  "same issue",
  "same incident",
  "still",
  "again",
  "update on",
  "previous",
  "ongoing",
  "as before",
];

export const scoreIntentPhrase: SignalScorer = (_candidate, request) => {
  const text = `${request.request_summary} ${request.goal ?? ""}`.toLowerCase();
  const matched = CONTINUE_PHRASES.filter((p) => text.includes(p));
  if (matched.length === 0) {
    return {
      name: "intent-phrase",
      kind: "positive",
      strength: 0,
      reason: "No continuation/follow-up phrases in request",
    };
  }
  return {
    name: "intent-phrase",
    kind: "positive",
    strength: Math.min(1, matched.length / 2),
    reason: `Request mentions ${matched.map((m) => `'${m}'`).join(", ")}`,
    evidence: { matched },
  };
};

// ----- conflict signals ------------------------------------------------------

const TENANT_KEYS = [
  "tenant",
  "customer",
  "client",
  "account",
  "org",
];

function extractTenantHints(contexts: string[]): string[] {
  return contexts
    .map((c) => {
      const match = c.match(/^(?:tenant|customer|client|account|org)\s*[:=]\s*(.+)$/i);
      return match ? match[1].trim().toLowerCase() : "";
    })
    .filter(Boolean);
}

export const scoreTenantConflict: SignalScorer = (candidate, request) => {
  const requestTenants = extractTenantHints(request.contexts);
  if (requestTenants.length === 0) {
    return {
      name: "tenant-conflict",
      kind: "conflict",
      strength: 0,
      reason: "Request has no explicit tenant/customer context",
    };
  }
  const corpus = docCorpus(candidate).toLowerCase();
  // Find tenant tokens mentioned in the doc but not in the request.
  const docTenantMentions = new Set<string>();
  for (const key of TENANT_KEYS) {
    const regex = new RegExp(`${key}\\s*[:=]?\\s*['"\`]?([a-z0-9_-]+)`, "gi");
    let match: RegExpExecArray | null;
    while ((match = regex.exec(corpus)) !== null) {
      const val = match[1].toLowerCase();
      if (val) docTenantMentions.add(val);
    }
  }
  if (docTenantMentions.size === 0) {
    return {
      name: "tenant-conflict",
      kind: "conflict",
      strength: 0,
      reason: "Doc has no explicit tenant mentions",
    };
  }
  const sharesTenant = requestTenants.some((t) => docTenantMentions.has(t));
  if (sharesTenant) {
    return {
      name: "tenant-conflict",
      kind: "conflict",
      strength: 0,
      reason: "Tenant matches",
    };
  }
  return {
    name: "tenant-conflict",
    kind: "conflict",
    strength: 1,
    reason: `Doc tenants {${[...docTenantMentions].join(", ")}} disjoint from request tenants {${requestTenants.join(", ")}}`,
    evidence: { requestTenants, docTenantMentions: [...docTenantMentions] },
  };
};

function topDirectories(paths: string[]): Set<string> {
  const out = new Set<string>();
  for (const p of paths) {
    const segments = p.split("/").filter(Boolean);
    if (segments.length === 0) continue;
    out.add(segments[0].toLowerCase());
  }
  return out;
}

export const scoreRepoConflict: SignalScorer = (candidate, request) => {
  if (request.files.length === 0) {
    return {
      name: "repo-conflict",
      kind: "conflict",
      strength: 0,
      reason: "Request lists no files; cannot detect repo conflict",
    };
  }
  const corpus = docCorpus(candidate).toLowerCase();
  // Extract /-style paths that look like file references from the doc.
  const docFileMatches = corpus.match(/[a-z0-9_.-]+\/[a-z0-9_./-]+/g) ?? [];
  if (docFileMatches.length === 0) {
    return {
      name: "repo-conflict",
      kind: "conflict",
      strength: 0,
      reason: "Doc has no file-style references",
    };
  }
  const docTopDirs = topDirectories(docFileMatches);
  const requestTopDirs = topDirectories(request.files);
  if (requestTopDirs.size === 0) {
    return {
      name: "repo-conflict",
      kind: "conflict",
      strength: 0,
      reason: "Could not infer request top-level directories",
    };
  }
  let shared = 0;
  for (const dir of requestTopDirs) {
    if (docTopDirs.has(dir)) shared += 1;
  }
  if (shared > 0) {
    return {
      name: "repo-conflict",
      kind: "conflict",
      strength: 0,
      reason: "Repos/subsystems overlap",
    };
  }
  return {
    name: "repo-conflict",
    kind: "conflict",
    strength: 1,
    reason: `Doc top-dirs {${[...docTopDirs].slice(0, 4).join(", ")}} disjoint from request top-dirs {${[...requestTopDirs].join(", ")}}`,
    evidence: {
      docTopDirs: [...docTopDirs],
      requestTopDirs: [...requestTopDirs],
    },
  };
};

const ERROR_FAMILY_TOKENS = [
  "timeout",
  "permission",
  "auth",
  "401",
  "403",
  "404",
  "500",
  "502",
  "503",
  "504",
  "syntax",
  "null",
  "undefined",
  "deadlock",
  "oom",
  "memory",
  "cors",
  "ssl",
  "tls",
  "dns",
];

function errorFamilies(values: string[]): Set<string> {
  const families = new Set<string>();
  for (const v of values) {
    const lower = v.toLowerCase();
    for (const fam of ERROR_FAMILY_TOKENS) {
      if (lower.includes(fam)) families.add(fam);
    }
  }
  return families;
}

export const scoreErrorFamilyConflict: SignalScorer = (candidate, request) => {
  if (request.errors.length === 0) {
    return {
      name: "error-family-conflict",
      kind: "conflict",
      strength: 0,
      reason: "Request lists no error strings",
    };
  }
  const requestFamilies = errorFamilies(request.errors);
  if (requestFamilies.size === 0) {
    return {
      name: "error-family-conflict",
      kind: "conflict",
      strength: 0,
      reason: "Request errors do not match known families",
    };
  }
  const corpusTokens = tokenize(docCorpus(candidate));
  const docFamilies = new Set<string>();
  for (const tok of corpusTokens) {
    if (ERROR_FAMILY_TOKENS.includes(tok)) docFamilies.add(tok);
  }
  if (docFamilies.size === 0) {
    return {
      name: "error-family-conflict",
      kind: "conflict",
      strength: 0,
      reason: "Doc does not mention any error family",
    };
  }
  let shared = 0;
  for (const fam of requestFamilies) if (docFamilies.has(fam)) shared += 1;
  if (shared > 0) {
    return {
      name: "error-family-conflict",
      kind: "conflict",
      strength: 0,
      reason: "Error families overlap",
    };
  }
  return {
    name: "error-family-conflict",
    kind: "conflict",
    strength: 1,
    reason: `Doc error families {${[...docFamilies].join(", ")}} disjoint from request {${[...requestFamilies].join(", ")}}`,
    evidence: {
      docFamilies: [...docFamilies],
      requestFamilies: [...requestFamilies],
    },
  };
};

const TERMINAL_MARKERS = [
  "## outcome",
  "## resolution",
  "status: done",
  "status: closed",
  "status: resolved",
  "status: superseded",
  "marked complete",
  "incident closed",
];

export const scoreTerminalStateConflict: SignalScorer = (candidate, request) => {
  const detailsText = flattenDetailsText(candidate.details_markdown_sections).toLowerCase();
  const terminalHits = TERMINAL_MARKERS.filter((m) => detailsText.includes(m));
  if (terminalHits.length === 0) {
    return {
      name: "terminal-state-conflict",
      kind: "conflict",
      strength: 0,
      reason: "Doc shows no terminal markers",
    };
  }
  const requestText = `${request.request_summary} ${request.goal ?? ""}`.toLowerCase();
  const continuesPrior = CONTINUE_PHRASES.some((p) => requestText.includes(p));
  if (continuesPrior) {
    return {
      name: "terminal-state-conflict",
      kind: "conflict",
      strength: 0,
      reason: "Doc is terminal but request explicitly continues prior work",
    };
  }
  return {
    name: "terminal-state-conflict",
    kind: "conflict",
    strength: 1,
    reason: `Doc is terminal (matched ${terminalHits[0]}) and request reads as new work`,
    evidence: { terminalHits },
  };
};

export const DEFAULT_SIGNALS: readonly SignalScorer[] = [
  scoreTitleOverlap,
  scoreFileOverlap,
  scoreSymbolOverlap,
  scoreErrorOverlap,
  scoreAnchorOverlap,
  scoreCollaboratorOverlap,
  scoreRecency,
  scoreIntentPhrase,
  scoreTenantConflict,
  scoreRepoConflict,
  scoreErrorFamilyConflict,
  scoreTerminalStateConflict,
];

export type { SignalResult };
