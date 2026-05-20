import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import { loadConfig } from "./config.js";
import { enderaiFetch, type ResponseSummary } from "./http.js";
import { rewriteDeprecatedApiPath } from "./deprecatedPathRewrite.js";
import {
  getLocalSkillsDirectory,
  syncSkillUseResultToLocalFiles,
  type SkillSyncResult,
} from "./skillSync.js";
import {
  beginDocument,
  createActiveDocumentState,
  finishDocument,
  updateDocument,
  type ActiveDocumentState,
} from "./v2Documents/index.js";

export type McpServerOptions = {
  // Optional backend bearer token provider used for all tool calls in this server instance.
  // This enables a hosted MCP server to act per user by binding the validated MCP token
  // to a session while still supporting token rotation during that session.
  backendBearerTokenProvider?: () => string | undefined;
};

const AUDIT_MAX_BYTES = 48_000;
const AUDIT_PREVIEW_CHARS = 8_000;
const DEFAULT_CONTEXT_PACK_CASE_LIMIT = 3;
const DEFAULT_SKILL_LIMIT = 3;
const DEFAULT_REUSE_WINDOW_SECONDS = 60 * 60 * 24 * 30;
const DEFAULT_THREAD_TITLE_MAX_CHARS = 255;
const POLICY_VERSION = "topic_case_v1";
const WORKFLOW_MODEL = "topic_case_v1";
const AUTH_MODEL = "single_token_hosted_mcp";
const UuidStringSchema = z.string().uuid();

const REDACT_KEYS = new Set([
  "authorization",
  "x-enderai-backend-token",
  "x-enderai-backend-authorization",
  "bearertoken",
  "password",
  "token",
  "access_token",
  "refresh_token",
  "client_secret",
  "secret",
  "secret_key",
]);

const TERMINAL_CASE_STATUSES = new Set([
  "aborted",
  "cancelled",
  "canceled",
  "closed",
  "complete",
  "completed",
  "done",
  "failed",
  "resolved",
]);

const CommandRecordSchema = z
  .object({
    cmd: z.string().min(1),
    purpose: z.string().optional(),
    salient_result: z.string().optional(),
    ts: z.string().optional(),
  })
  .strict();

const HypothesisRecordSchema = z
  .object({
    statement: z.string().min(1),
    status: z.enum(["open", "supported", "disproven"]).optional(),
    evidence: z.string().optional(),
    ts: z.string().optional(),
  })
  .strict();

const ChangeRecordSchema = z
  .object({
    kind: z.enum(["code", "config", "infra", "docs", "test"]).optional(),
    summary: z.string().min(1),
    files: z.array(z.string()).optional(),
    refs: z.array(z.string()).optional(),
    ts: z.string().optional(),
  })
  .strict();

const BeginCaseArgsSchema = z
  .object({
    topic_title: z.string().min(1).optional(),
    workflow_key: z.string().min(1).optional(),
    intent_key: z.string().min(1).optional(),
    goal: z.string().optional(),
    acceptance_criteria: z.string().optional(),
    request_summary: z.string().min(1),
    case_title: z.string().min(1).optional(),
    targets: z.array(z.unknown()).optional(),
    aliases: z.array(z.string()).optional(),
    files: z.array(z.string()).optional(),
    symbols: z.array(z.string()).optional(),
    errors: z.array(z.string()).optional(),
    symptoms: z.array(z.string()).optional(),
    contexts: z.array(z.string()).optional(),
    auto_hydrate: z.boolean().optional(),
    max_cases_per_topic: z.number().int().positive().optional(),
    reuse_within_seconds: z.number().int().nonnegative().optional(),
  })
  .strict();

type BeginCaseArgs = z.infer<typeof BeginCaseArgsSchema>;

const UpdateCaseArgsSchema = z
  .object({
    case_id: z.string().uuid().optional(),
    title: z.string().min(1).optional(),
    input_summary: z.string().optional(),
    summary_current: z.string().optional(),
    files: z.array(z.string()).optional(),
    symbols: z.array(z.string()).optional(),
    errors: z.array(z.string()).optional(),
    symptoms: z.array(z.string()).optional(),
    commands: z.array(CommandRecordSchema).optional(),
    hypotheses: z.array(HypothesisRecordSchema).optional(),
    changes: z.array(ChangeRecordSchema).optional(),
    outcome: z.string().optional(),
    next_steps: z.array(z.string()).optional(),
    progress_note: z.string().min(1).optional(),
    progress_data: z.record(z.unknown()).optional(),
  })
  .strict()
  .refine(
    (value) =>
      [
        value.title,
        value.input_summary,
        value.summary_current,
        value.files,
        value.symbols,
        value.errors,
        value.symptoms,
        value.commands,
        value.hypotheses,
        value.changes,
        value.outcome,
        value.next_steps,
        value.progress_note,
      ].some((item) => item !== undefined),
    {
      message: "Provide one or more case fields or progress_note.",
    },
  );

const FinishCaseArgsSchema = z
  .object({
    case_id: z.string().uuid().optional(),
    status: z.string().default("done"),
    summary_current: z.string().optional(),
    outcome: z.string().optional(),
    files: z.array(z.string()).optional(),
    symbols: z.array(z.string()).optional(),
    errors: z.array(z.string()).optional(),
    symptoms: z.array(z.string()).optional(),
    commands: z.array(CommandRecordSchema).optional(),
    hypotheses: z.array(HypothesisRecordSchema).optional(),
    changes: z.array(ChangeRecordSchema).optional(),
    next_steps: z.array(z.string()).optional(),
    closing_note: z.string().min(1).optional(),
    closing_data: z.record(z.unknown()).optional(),
  })
  .strict();

const BeginDocumentArgsSchema = z
  .object({
    request_summary: z.string().min(1),
    goal: z.string().optional(),
    acceptance_criteria: z.string().optional(),
    title: z.string().min(1).optional(),
    collaborators: z.array(z.string()).optional(),
    files: z.array(z.string()).optional(),
    symbols: z.array(z.string()).optional(),
    errors: z.array(z.string()).optional(),
    contexts: z.array(z.string()).optional(),
    document_id: z.string().uuid().optional(),
    reuse_within_seconds: z.number().int().nonnegative().optional(),
    force_new: z.boolean().optional(),
    visibility: z.enum(["private", "organization"]).optional(),
    demo: z.boolean().optional(),
  })
  .strict();

const DocumentDetailsSectionSchema = z
  .object({
    anchor_id: z.string().min(1),
    markdown: z.string(),
  })
  .strict();

const DocumentCommandSchema = z
  .object({
    cmd: z.string().min(1),
    purpose: z.string().optional(),
    salient_result: z.string().optional(),
    ts: z.string().optional(),
  })
  .strict();

const DocumentDecisionSchema = z
  .object({
    statement: z.string().min(1),
    rationale: z.string().optional(),
  })
  .strict();

const DocumentChangeSchema = z
  .object({
    kind: z.string().min(1),
    summary: z.string().min(1),
    files: z.array(z.string()).optional(),
  })
  .strict();

const UpdateDocumentArgsSchema = z
  .object({
    document_id: z.string().uuid().optional(),
    title: z.string().min(1).optional(),
    description: z.string().optional(),
    human_summary: z.string().optional(),
    summary_points: z.array(z.string()).optional(),
    ai_generated_summary: z.string().optional(),
    collaborators: z.array(z.string()).optional(),
    details_sections: z.array(DocumentDetailsSectionSchema).optional(),
    commands: z.array(DocumentCommandSchema).optional(),
    files: z.array(z.string()).optional(),
    links: z.array(z.string()).optional(),
    decisions: z.array(DocumentDecisionSchema).optional(),
    changes: z.array(DocumentChangeSchema).optional(),
    open_questions: z.array(z.string()).optional(),
    progress_note: z.string().optional(),
    visibility: z.enum(["private", "organization"]).optional(),
    demo: z.boolean().optional(),
  })
  .strict();

const FinishDocumentArgsSchema = z
  .object({
    document_id: z.string().uuid().optional(),
    outcome: z.string().optional(),
    validation: z.array(z.string()).optional(),
    follow_ups: z.array(z.string()).optional(),
    status: z.enum(["done", "paused", "blocked", "superseded"]).optional(),
    closing_note: z.string().optional(),
    demo: z.boolean().optional(),
  })
  .strict();

const UseSkillArgsSchema = z
  .object({
    skill_id: z.string().uuid().optional(),
    case_id: z.string().uuid().optional(),
    title: z.string().min(1).optional(),
    request_summary: z.string().min(1).optional(),
    aliases: z.array(z.string()).optional(),
    files: z.array(z.string()).optional(),
    symbols: z.array(z.string()).optional(),
    errors: z.array(z.string()).optional(),
    symptoms: z.array(z.string()).optional(),
    contexts: z.array(z.string()).optional(),
    max_skills: z.number().int().positive().max(10).optional(),
    demo: z.boolean().optional(),
  })
  .strict();

type UseSkillArgs = z.infer<typeof UseSkillArgsSchema>;

const EnderaiRequestArgsSchema = z
  .object({
    method: z.string().min(1),
    path: z.string().min(1),
    query: z.record(z.unknown()).optional(),
    headers: z.record(z.string()).optional(),
    json: z.unknown().optional(),
    text: z.string().optional(),
    bearerToken: z.string().optional(),
    unsafe_write_reason: z.string().min(1).optional(),
    timeoutMs: z.number().int().positive().optional(),
    audit: z
      .object({
        intent: z.string().min(1).optional(),
        execution_id: z.string().uuid().optional(),
        run_id: z.string().uuid().optional(),
      })
      .optional(),
  })
  .refine((value) => !(value.json !== undefined && value.text !== undefined), {
    message: 'Provide only one of "json" or "text".',
  });

const stringArrayJsonSchema = { type: "array", items: { type: "string" } };
const looseObjectJsonSchema = { type: "object", additionalProperties: true };
const commandRecordJsonSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    cmd: { type: "string", description: "Command line that was run." },
    purpose: { type: "string", description: "Why the command was run." },
    salient_result: {
      type: "string",
      description: "Short result summary worth preserving in the case document.",
    },
    ts: { type: "string", description: "Optional ISO timestamp." },
  },
  required: ["cmd"],
};
const hypothesisRecordJsonSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    statement: { type: "string", description: "Hypothesis statement." },
    status: {
      type: "string",
      enum: ["open", "supported", "disproven"],
      description: "Current hypothesis status.",
    },
    evidence: { type: "string", description: "Evidence supporting the status." },
    ts: { type: "string", description: "Optional ISO timestamp." },
  },
  required: ["statement"],
};
const changeRecordJsonSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    kind: {
      type: "string",
      enum: ["code", "config", "infra", "docs", "test"],
      description: "Kind of change made.",
    },
    summary: { type: "string", description: "Short change summary." },
    files: stringArrayJsonSchema,
    refs: stringArrayJsonSchema,
    ts: { type: "string", description: "Optional ISO timestamp." },
  },
  required: ["summary"],
};

const taskforceUsageJsonSchema = {
  type: "object",
  additionalProperties: false,
  description:
    "Per-turn token usage from the agent's most recent assistant turn. When supplied, the backend prices it against the model's pricing snapshot, records a tokens.consumed event, and computes attributable savings (cache reads always; summary-only reads when view_consulted is set to 'summary'; reuse-on-begin when this call reused an existing document). Omit when the turn has no meaningful token usage to report.",
  properties: {
    model_id: {
      type: "string",
      description:
        "Anthropic model id used for the turn (e.g. 'claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001'). Required when usage is supplied.",
    },
    input_tokens: {
      type: "integer",
      minimum: 0,
      description: "Base input tokens billed this turn (excludes cache reads and cache creation).",
    },
    output_tokens: {
      type: "integer",
      minimum: 0,
      description: "Output tokens generated this turn.",
    },
    cache_read_input_tokens: {
      type: "integer",
      minimum: 0,
      description:
        "Tokens served from the prompt cache this turn. Drives the cache savings calculation.",
    },
    cache_creation_input_tokens: {
      type: "integer",
      minimum: 0,
      description: "Tokens written to the prompt cache this turn.",
    },
    view_consulted: {
      type: "string",
      enum: ["summary", "details", "both"],
      description:
        "Which view of the active document the agent consulted before this turn. Set to 'summary' when you answered from Summary alone without expanding Details — that unlocks the summary-only savings calculation.",
    },
    occurred_at: {
      type: "string",
      description: "Optional ISO timestamp. Defaults to the server clock.",
    },
  },
  required: ["model_id"],
};

function shouldRedactKey(key: string): boolean {
  const normalized = key.trim().toLowerCase();
  if (!normalized) return false;
  return REDACT_KEYS.has(normalized);
}

function redactSecrets(value: unknown, keyHint?: string): unknown {
  if (keyHint && shouldRedactKey(keyHint)) return "[REDACTED]";
  if (value === null) return null;
  if (value === undefined) return undefined;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (Array.isArray(value)) return value.map((entry) => redactSecrets(entry));
  if (typeof value !== "object") return String(value);

  const obj = value as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const [key, entry] of Object.entries(obj)) {
    out[key] = redactSecrets(entry, key);
  }
  return out;
}

function capJson(value: unknown): unknown {
  try {
    const raw = JSON.stringify(value);
    const bytes = Buffer.byteLength(raw, "utf8");
    if (bytes <= AUDIT_MAX_BYTES) return value;
    return {
      _truncated: true,
      _original_bytes: bytes,
      _preview: raw.slice(0, AUDIT_PREVIEW_CHARS),
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { _unserializable: true, _error: msg };
  }
}

function trimToUndefined(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

function slugifyWorkflowKey(value: string): string {
  const slug = value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return slug || "topic";
}

function humanizeWorkflowKey(value: string): string {
  return value
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function isTerminalCaseStatus(status: string | undefined): boolean {
  const normalized = trimToUndefined(status)?.toLowerCase();
  return normalized ? TERMINAL_CASE_STATUSES.has(normalized) : false;
}

function isWriteLikeMethod(method: string): boolean {
  const normalized = method.trim().toUpperCase();
  return !["GET", "HEAD", "OPTIONS"].includes(normalized);
}

function normalizeJsonArgument(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (!trimmed) return value;
  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
}

function isClosedCaseRecord(caseData: Record<string, any>): boolean {
  const status = typeof caseData.status === "string" ? caseData.status : undefined;
  const closedAt =
    typeof caseData.closed_at === "string" ? trimToUndefined(caseData.closed_at) : undefined;
  return Boolean(closedAt) || isTerminalCaseStatus(status);
}

function asRecord(value: unknown): Record<string, any> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, any>;
}

function pruneUndefined<T extends Record<string, unknown>>(value: T): T {
  return Object.fromEntries(
    Object.entries(value).filter(([, entry]) => entry !== undefined),
  ) as T;
}

function trimToMaxLength(value: string, max: number): string {
  return value.length > max ? value.slice(0, max) : value;
}

function dedupeNonEmptyStrings(values: Array<string | undefined>): string[] | undefined {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const trimmed = trimToUndefined(value);
    if (!trimmed || seen.has(trimmed)) continue;
    seen.add(trimmed);
    out.push(trimmed);
  }
  return out.length > 0 ? out : undefined;
}

function describeTarget(target: unknown): string | undefined {
  if (typeof target === "string") return trimToUndefined(target);
  if (target && typeof target === "object" && !Array.isArray(target)) {
    const record = target as Record<string, unknown>;
    const parts = Object.entries(record)
      .map(([key, value]) => {
        if (value === null || value === undefined) return undefined;
        if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
          return `${key}:${String(value)}`;
        }
        return undefined;
      })
      .filter((value): value is string => Boolean(value));
    if (parts.length > 0) return parts.join(" ");
  }
  try {
    return trimToUndefined(JSON.stringify(target));
  } catch {
    return undefined;
  }
}

function collectContextHints(args: BeginCaseArgs): string[] | undefined {
  return dedupeNonEmptyStrings([
    ...(args.contexts ?? []),
    ...(args.targets ?? []).map((target) => describeTarget(target)),
  ]);
}

function buildTopicMatchPayload(
  args: BeginCaseArgs,
  requestSummary: string,
  caseTitle: string | undefined,
): Record<string, unknown> {
  return pruneUndefined({
    title: caseTitle ?? requestSummary,
    request_summary: requestSummary,
    aliases: args.aliases,
    files: args.files,
    symbols: args.symbols,
    errors: args.errors,
    symptoms: args.symptoms,
    contexts: collectContextHints(args),
  });
}

function collectArrayField(record: Record<string, any>, key: string): string[] {
  const value = record[key];
  return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
}

function buildUseSkillPayload(
  args: UseSkillArgs,
  caseData: Record<string, any> | null,
): Record<string, unknown> {
  const contextPack = asRecord(caseData?.context_pack_snapshot);
  const contextTakeaways = Array.isArray(contextPack.pinned_takeaways)
    ? contextPack.pinned_takeaways.filter((item) => typeof item === "string")
    : [];
  const contextQuestions = Array.isArray(contextPack.questions)
    ? contextPack.questions.filter((item) => typeof item === "string")
    : [];
  const caseTitle = typeof caseData?.title === "string" ? caseData.title : undefined;
  const caseInputSummary =
    typeof caseData?.input_summary === "string" ? caseData.input_summary : undefined;
  const caseSummary =
    typeof caseData?.summary_current === "string" ? caseData.summary_current : undefined;
  const topicSummary =
    typeof contextPack.topic_summary === "string" ? contextPack.topic_summary : undefined;
  const resolvedCaseId =
    args.case_id ?? (typeof caseData?.id === "string" ? caseData.id : undefined);

  return pruneUndefined({
    skill_id: args.skill_id,
    case_id: resolvedCaseId,
    title: trimToUndefined(args.title) ?? trimToUndefined(caseTitle),
    request_summary:
      trimToUndefined(args.request_summary) ??
      trimToUndefined(caseInputSummary) ??
      trimToUndefined(caseSummary),
    aliases: args.aliases,
    files: dedupeNonEmptyStrings([
      ...(args.files ?? []),
      ...collectArrayField(caseData ?? {}, "files"),
    ]),
    symbols: dedupeNonEmptyStrings([
      ...(args.symbols ?? []),
      ...collectArrayField(caseData ?? {}, "symbols"),
    ]),
    errors: dedupeNonEmptyStrings([
      ...(args.errors ?? []),
      ...collectArrayField(caseData ?? {}, "errors"),
    ]),
    symptoms: dedupeNonEmptyStrings([
      ...(args.symptoms ?? []),
      ...collectArrayField(caseData ?? {}, "symptoms"),
    ]),
    contexts: dedupeNonEmptyStrings([
      ...(args.contexts ?? []),
      caseSummary,
      topicSummary,
      ...contextTakeaways,
      ...contextQuestions,
    ]),
    max_skills: args.max_skills ?? DEFAULT_SKILL_LIMIT,
  });
}

function hasSkillMatchSignals(payload: Record<string, unknown>): boolean {
  return (
    Boolean(payload.skill_id) ||
    Boolean(payload.case_id) ||
    Boolean(payload.title) ||
    Boolean(payload.request_summary) ||
    (Array.isArray(payload.files) && payload.files.length > 0) ||
    (Array.isArray(payload.symbols) && payload.symbols.length > 0) ||
    (Array.isArray(payload.errors) && payload.errors.length > 0) ||
    (Array.isArray(payload.symptoms) && payload.symptoms.length > 0) ||
    (Array.isArray(payload.contexts) && payload.contexts.length > 0)
  );
}

function summarizeSkill(skillValue: unknown): Record<string, unknown> | null {
  const skill = asRecord(skillValue);
  const id = typeof skill.id === "string" ? skill.id : undefined;
  if (!id) return null;
  return pruneUndefined({
    id,
    title: typeof skill.title === "string" ? skill.title : undefined,
    slug: typeof skill.slug === "string" ? skill.slug : undefined,
    confidence: typeof skill.confidence === "string" ? skill.confidence : undefined,
    source_type: typeof skill.source_type === "string" ? skill.source_type : undefined,
    updated_at: typeof skill.updated_at === "string" ? skill.updated_at : undefined,
  });
}

function summarizeSkillCandidate(candidateValue: unknown): Record<string, unknown> | null {
  const candidate = asRecord(candidateValue);
  const skill = summarizeSkill(candidate.skill);
  if (!skill) return null;
  return pruneUndefined({
    skill,
    score: typeof candidate.score === "number" ? candidate.score : undefined,
    confidence:
      typeof candidate.confidence === "string" ? candidate.confidence : undefined,
    matched_signals: Array.isArray(candidate.matched_signals)
      ? candidate.matched_signals.filter((item) => typeof item === "string")
      : undefined,
    reasoning: Array.isArray(candidate.reasoning)
      ? candidate.reasoning.filter((item) => typeof item === "string")
      : undefined,
  });
}

function summarizeSkillUseForHydration(
  skillUseData: unknown,
  localSkillSync: SkillSyncResult,
): Record<string, unknown> {
  const data = asRecord(skillUseData);
  const matchedSkills = Array.isArray(data.matched_skills)
    ? data.matched_skills
        .map((candidate) => summarizeSkillCandidate(candidate))
        .filter((candidate): candidate is Record<string, unknown> => Boolean(candidate))
    : [];
  return {
    status: localSkillSync.local_skill_files.length > 0 ? "synced" : "none",
    selected_skill: summarizeSkill(data.selected_skill),
    matched_skills: matchedSkills,
    matched_skill_count: matchedSkills.length,
    confidence: typeof data.confidence === "string" ? data.confidence : "low",
    matched_signals: Array.isArray(data.matched_signals)
      ? data.matched_signals.filter((item) => typeof item === "string")
      : [],
    local_skill_sync: localSkillSync,
  };
}

async function tryHydrateSkillsForCase(params: {
  bearerToken?: string;
  caseData: Record<string, any>;
}): Promise<Record<string, unknown>> {
  const payload = buildUseSkillPayload({ max_skills: DEFAULT_SKILL_LIMIT }, params.caseData);
  if (!hasSkillMatchSignals(payload)) {
    return {
      status: "skipped",
      reason: "No case or request signals were available for Skill matching.",
      local_skill_sync: {
        directory: getLocalSkillsDirectory(),
        index_path: null,
        local_skill_files: [],
        agent_instructions: [
          "No EnderAI Skill matching was attempted because no signals were available.",
        ],
      },
    };
  }

  try {
    const skillRes = await enderaiFetch({
      method: "POST",
      path: "/api/v1/skills/use",
      bearerToken: params.bearerToken,
      json: payload,
    });
    if (!skillRes.ok) {
      return {
        status: "failed",
        error: extractErrorDetail(skillRes),
        backend_status: skillRes.status,
        local_skill_sync: {
          directory: getLocalSkillsDirectory(),
          index_path: null,
          local_skill_files: [],
          agent_instructions: [
            "EnderAI Skill matching failed. Continue with Topic/Case context and retry enderai_use_skill if needed.",
          ],
        },
      };
    }

    const localSkillSync = await syncSkillUseResultToLocalFiles(skillRes.data);
    return summarizeSkillUseForHydration(skillRes.data, localSkillSync);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return {
      status: "failed",
      error: msg,
      local_skill_sync: {
        directory: getLocalSkillsDirectory(),
        index_path: null,
        local_skill_files: [],
        agent_instructions: [
          "EnderAI Skill matching or local Skill sync failed. Continue with Topic/Case context and retry enderai_use_skill if needed.",
        ],
      },
    };
  }
}

function extractExecutionStartIds(
  resData: unknown,
): { executionId?: string; threadId?: string } {
  const data = asRecord(resData);
  const execution = asRecord(data.execution);
  const thread = asRecord(data.thread);
  return {
    executionId:
      typeof execution.id === "string" ? execution.id : undefined,
    threadId: typeof thread.id === "string" ? thread.id : undefined,
  };
}

function confidenceRank(value: unknown): number {
  const normalized =
    typeof value === "string" ? trimToUndefined(value)?.toLowerCase() : undefined;
  if (normalized === "high") return 3;
  if (normalized === "medium") return 2;
  if (normalized === "low") return 1;
  return 0;
}

function topicIsWithinReuseWindow(
  topic: Record<string, any>,
  reuseWithinSeconds: number | undefined,
): boolean {
  if (reuseWithinSeconds === undefined) return true;
  const lastUsedAt =
    typeof topic.last_used_at === "string" ? trimToUndefined(topic.last_used_at) : undefined;
  if (!lastUsedAt) return true;
  const lastUsedMs = Date.parse(lastUsedAt);
  if (Number.isNaN(lastUsedMs)) return true;
  return Date.now() - lastUsedMs <= reuseWithinSeconds * 1000;
}

function selectReusableMatchedTopic(
  matchData: unknown,
  minimumConfidence: "high" | "medium" | "low",
  reuseWithinSeconds: number | undefined,
): Record<string, any> | undefined {
  const data = asRecord(matchData);
  const candidates = Array.isArray(data.candidates) ? data.candidates : [];
  for (const candidateValue of candidates) {
    const candidate = asRecord(candidateValue);
    const topic = asRecord(candidate.topic);
    if (typeof topic.id !== "string") continue;
    if (confidenceRank(candidate.confidence) < confidenceRank(minimumConfidence)) continue;
    if (!topicIsWithinReuseWindow(topic, reuseWithinSeconds)) continue;
    return topic;
  }
  return undefined;
}

function extractErrorDetail(res: ResponseSummary): string {
  const data = res.data;
  if (typeof data === "string" && data.trim()) return data.trim();

  const obj = asRecord(data);
  if (typeof obj.detail === "string" && obj.detail.trim()) return obj.detail.trim();
  if (Array.isArray(obj.detail)) return JSON.stringify(obj.detail);
  if (typeof obj.message === "string" && obj.message.trim()) return obj.message.trim();
  return `HTTP ${res.status}`;
}

function toolJson(value: unknown): { content: Array<{ type: "text"; text: string }> } {
  return { content: [{ type: "text", text: JSON.stringify(value, null, 2) }] };
}

function toolError(message: string): {
  content: Array<{ type: "text"; text: string }>;
  isError: true;
} {
  return { content: [{ type: "text", text: message }], isError: true };
}

export function createMcpServer(opts: McpServerOptions = {}): Server {
  const server = new Server(
    { name: "enderai-api", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );

  const auditState: {
    executionId?: string;
    threadId?: string;
    depth: number;
  } = { depth: 0 };

  const activeDocumentState: ActiveDocumentState = createActiveDocumentState();

  function setActiveCaseContext(caseId?: string, topicId?: string): void {
    if (caseId) auditState.executionId = caseId;
    if (topicId) auditState.threadId = topicId;
  }

  function clearActiveCaseContext(): void {
    delete auditState.executionId;
    delete auditState.threadId;
  }

  async function reconcileActiveCaseContext(params: {
    bearerToken?: string;
  } = {}): Promise<{
    caseId: string | null;
    topicId: string | null;
    caseData: Record<string, any> | null;
    cleared: boolean;
  }> {
    const activeCaseId = auditState.executionId;
    if (!activeCaseId) {
      return {
        caseId: null,
        topicId: auditState.threadId ?? null,
        caseData: null,
        cleared: false,
      };
    }

    if (!UuidStringSchema.safeParse(activeCaseId).success) {
      clearActiveCaseContext();
      return { caseId: null, topicId: null, caseData: null, cleared: true };
    }

    const caseRes = await enderaiFetch({
      method: "GET",
      path: `/api/v1/cases/${activeCaseId}`,
      bearerToken: params.bearerToken,
    });

    if (caseRes.status === 404) {
      clearActiveCaseContext();
      return { caseId: null, topicId: null, caseData: null, cleared: true };
    }

    if (!caseRes.ok) {
      return {
        caseId: activeCaseId,
        topicId: auditState.threadId ?? null,
        caseData: null,
        cleared: false,
      };
    }

    const caseData = asRecord(caseRes.data);
    const topicId =
      typeof caseData.topic_id === "string" ? caseData.topic_id : auditState.threadId ?? null;
    if (isClosedCaseRecord(caseData)) {
      clearActiveCaseContext();
      return { caseId: null, topicId: null, caseData, cleared: true };
    }

    setActiveCaseContext(activeCaseId, topicId ?? undefined);
    return {
      caseId: activeCaseId,
      topicId,
      caseData,
      cleared: false,
    };
  }

  async function resolveCaseId(
    explicitCaseId: string | undefined,
    toolName: string,
    bearerToken?: string,
  ): Promise<string> {
    await reconcileActiveCaseContext({ bearerToken });
    if (explicitCaseId) {
      if (auditState.executionId && auditState.executionId !== explicitCaseId) {
        throw new Error(
          `${toolName} is currently attached to case ${auditState.executionId}. Run enderai_finish_case before switching to case ${explicitCaseId}.`,
        );
      }
      return explicitCaseId;
    }
    if (auditState.executionId) return auditState.executionId;
    throw new Error(
      `${toolName} requires an active case. Run enderai_begin_case first or provide case_id.`,
    );
  }

  async function tryCreateRunEvent(params: {
    bearerToken?: string;
    executionId?: string;
    type: string;
    message: string;
    data: unknown;
  }): Promise<void> {
    if (!params.executionId) return;
    if (!params.bearerToken) return;
    if (auditState.depth > 0) return;

    auditState.depth += 1;
    try {
      await enderaiFetch({
        method: "POST",
        path: `/api/v1/cases/${params.executionId}/events`,
        bearerToken: params.bearerToken,
        json: {
          type: params.type,
          message: params.message,
          data: params.data,
        },
      });
    } catch {
      // Best-effort audit trail. Never fail the primary tool request.
    } finally {
      auditState.depth -= 1;
    }
  }

  async function tryAutoLinkLibraryItem(params: {
    bearerToken?: string;
    executionId?: string;
    artifactId?: string;
    createdAt?: string | null;
  }): Promise<unknown | null> {
    if (!params.executionId || !params.artifactId || !params.bearerToken) return null;
    if (auditState.depth > 0) return null;

    auditState.depth += 1;
    try {
      const res = await enderaiFetch({
        method: "POST",
        path: `/api/v1/executions/${params.executionId}/artifact-links`,
        bearerToken: params.bearerToken,
        json: {
          artifact_id: params.artifactId,
          relation: "created",
          created_at: params.createdAt ?? null,
        },
      });
      return res;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { _error: msg };
    } finally {
      auditState.depth -= 1;
    }
  }

  async function createExecutionEvent(params: {
    bearerToken?: string;
    caseId: string;
    type: string;
    message: string;
    data?: Record<string, unknown>;
  }): Promise<ResponseSummary> {
    return await enderaiFetch({
      method: "POST",
      path: `/api/v1/cases/${params.caseId}/events`,
      bearerToken: params.bearerToken,
      json: {
        type: params.type,
        message: params.message,
        data: params.data ?? {},
      },
    });
  }

  async function auditWorkflowTool(params: {
    bearerToken?: string;
    executionId?: string;
    message: string;
    tool: string;
    request: unknown;
    response: unknown;
  }): Promise<void> {
    await tryCreateRunEvent({
      bearerToken: params.bearerToken,
      executionId: params.executionId,
      type: "mcp",
      message: params.message,
      data: capJson(
        redactSecrets({
          tool: params.tool,
          request: params.request,
          response: params.response,
          execution_context: {
            execution_id: params.executionId ?? auditState.executionId ?? null,
            thread_id: auditState.threadId ?? null,
          },
        }),
      ),
    });
  }

  async function runSimpleGetTool(params: {
    name: string;
    path: string;
    message: string;
  }) {
    const sessionToken = opts.backendBearerTokenProvider?.();
    const res = await enderaiFetch({
      method: "GET",
      path: params.path,
      bearerToken: sessionToken,
    });

    await tryCreateRunEvent({
      bearerToken: sessionToken,
      executionId: auditState.executionId,
      type: "mcp",
      message: params.message,
      data: capJson(
        redactSecrets({
          tool: params.name,
          request: { method: "GET", path: params.path },
          response: res,
          execution_context: {
            execution_id: auditState.executionId ?? null,
            thread_id: auditState.threadId ?? null,
          },
        }),
      ),
    });

    return toolJson(res);
  }

  server.setRequestHandler(ListToolsRequestSchema, async () => {
    return {
      tools: [
        {
          name: "enderai_begin_case",
          description:
            "Use this first when a user initiates meaningful work. Starts a guided Topic/Case workflow, automatically hydrates relevant prior context by default, syncs matching generated EnderAI Skills to local markdown files when available, remembers the returned ids for this MCP session, and returns the ids needed for enderai_update_case and enderai_finish_case.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              topic_title: {
                type: "string",
                description: "Human-facing Topic title to group this case under.",
              },
              workflow_key: {
                type: "string",
                description:
                  "Stable workflow key for the Topic. If omitted, it is derived from topic_title.",
              },
              intent_key: {
                type: "string",
                description:
                  "Optional narrower intent key used by the backend's recent-topic reuse logic.",
              },
              goal: {
                type: "string",
                description: "Optional Topic goal to persist when a new Topic is created.",
              },
              acceptance_criteria: {
                type: "string",
                description:
                  "Optional Topic acceptance criteria to persist when a new Topic is created.",
              },
              request_summary: {
                type: "string",
                description: "Short statement of the new work request or problem to investigate.",
              },
              case_title: {
                type: "string",
                description: "Optional Case title if it should differ from the Topic title.",
              },
              targets: {
                type: "array",
                items: {},
                description: "Optional Execution targets to attach to the new case.",
              },
              aliases: {
                ...stringArrayJsonSchema,
                description: "Optional extra aliases to help ContextPack selection.",
              },
              files: {
                ...stringArrayJsonSchema,
                description: "Relevant files already known at case start.",
              },
              symbols: {
                ...stringArrayJsonSchema,
                description: "Relevant symbols already known at case start.",
              },
              errors: {
                ...stringArrayJsonSchema,
                description: "Known error strings to seed the case and ContextPack.",
              },
              symptoms: {
                ...stringArrayJsonSchema,
                description: "Known symptoms to seed the case and ContextPack.",
              },
              contexts: {
                ...stringArrayJsonSchema,
                description:
                  "Optional free-form context snippets to improve backend topic matching.",
              },
              auto_hydrate: {
                type: "boolean",
                description:
                  "Whether to build and attach a ContextPack immediately after the case starts. Defaults to true and should stay enabled for the standard EnderAI workflow.",
              },
              max_cases_per_topic: {
                type: "integer",
                description:
                  "Optional limit for how many prior cases each hydrated topic contributes to the ContextPack.",
                minimum: 1,
              },
              reuse_within_seconds: {
                type: "integer",
                description:
                  "Recent-topic reuse window passed to the backend execution-start endpoint.",
                minimum: 0,
              },
            },
            required: ["request_summary"],
          },
        },
        {
          name: "enderai_update_case",
          description:
            "Use this during an active case as material findings, commands, hypotheses, and changes develop. Requires a prior enderai_begin_case call in this MCP session unless case_id is supplied. Use enderai_finish_case, not this tool, to close a case.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              case_id: {
                type: "string",
                description:
                  "Optional explicit case id. If omitted, the active case from this MCP session is used.",
              },
              title: { type: "string", description: "Optional updated Case title." },
              input_summary: {
                type: "string",
                description: "Optional replacement for the case input summary.",
              },
              summary_current: {
                type: "string",
                description: "Current working summary of the case.",
              },
              files: {
                ...stringArrayJsonSchema,
                description: "Current canonical file list for the case.",
              },
              symbols: {
                ...stringArrayJsonSchema,
                description: "Current canonical symbol list for the case.",
              },
              errors: {
                ...stringArrayJsonSchema,
                description: "Current canonical error list for the case.",
              },
              symptoms: {
                ...stringArrayJsonSchema,
                description: "Current canonical symptom list for the case.",
              },
              commands: {
                type: "array",
                items: commandRecordJsonSchema,
                description: "Structured command history to keep on the case.",
              },
              hypotheses: {
                type: "array",
                items: hypothesisRecordJsonSchema,
                description: "Structured hypotheses to keep on the case.",
              },
              changes: {
                type: "array",
                items: changeRecordJsonSchema,
                description: "Structured change records to keep on the case.",
              },
              outcome: {
                type: "string",
                description: "Optional current outcome statement.",
              },
              next_steps: {
                ...stringArrayJsonSchema,
                description: "Optional next steps list for the case.",
              },
              progress_note: {
                type: "string",
                description:
                  "Optional progress note to append as an Execution event after the case patch succeeds.",
              },
              progress_data: {
                ...looseObjectJsonSchema,
                description: "Optional structured payload for the progress event.",
              },
            },
          },
        },
        {
          name: "enderai_use_skill",
          description:
            "Use this after enderai_begin_case and ContextPack hydration to retrieve and locally sync generated EnderAI Skill markdown for the active case. Skills are advisory workflow instructions generated from Topics, Cases, or ContextPacks.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              skill_id: {
                type: "string",
                description: "Optional explicit Skill id. If omitted, EnderAI matches skills from request and active-case signals.",
              },
              case_id: {
                type: "string",
                description:
                  "Optional explicit Case id. If omitted, the active case from enderai_begin_case is used when present.",
              },
              title: {
                type: "string",
                description: "Optional title signal for skill matching.",
              },
              request_summary: {
                type: "string",
                description: "Optional request summary signal for skill matching.",
              },
              aliases: {
                ...stringArrayJsonSchema,
                description: "Optional aliases or workflow hints for skill matching.",
              },
              files: {
                ...stringArrayJsonSchema,
                description: "Relevant file paths for skill matching.",
              },
              symbols: {
                ...stringArrayJsonSchema,
                description: "Relevant symbols for skill matching.",
              },
              errors: {
                ...stringArrayJsonSchema,
                description: "Known error strings for skill matching.",
              },
              symptoms: {
                ...stringArrayJsonSchema,
                description: "Known symptoms for skill matching.",
              },
              contexts: {
                ...stringArrayJsonSchema,
                description: "Free-form context snippets for skill matching.",
              },
              max_skills: {
                type: "integer",
                description: "Maximum matched skills to return. Defaults to 3.",
                minimum: 1,
                maximum: 10,
              },
              demo: {
                type: "boolean",
                description: "Read demo-mode skills instead of live user skills.",
              },
            },
          },
        },
        {
          name: "enderai_finish_case",
          description:
            "Use this as the terminal step to close the active Case with a terminal status. Requires a prior enderai_begin_case call in this MCP session unless case_id is supplied. Clears the active case context on success.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              case_id: {
                type: "string",
                description:
                  "Optional explicit case id. If omitted, the active case from this MCP session is used.",
              },
              status: {
                type: "string",
                description:
                  "Terminal case status. Defaults to done. Non-terminal statuses are rejected.",
              },
              summary_current: {
                type: "string",
                description: "Optional final case summary.",
              },
              outcome: {
                type: "string",
                description: "Optional final outcome statement.",
              },
              files: {
                ...stringArrayJsonSchema,
                description: "Optional final file list for the closed case.",
              },
              symbols: {
                ...stringArrayJsonSchema,
                description: "Optional final symbol list for the closed case.",
              },
              errors: {
                ...stringArrayJsonSchema,
                description: "Optional final error list for the closed case.",
              },
              symptoms: {
                ...stringArrayJsonSchema,
                description: "Optional final symptom list for the closed case.",
              },
              commands: {
                type: "array",
                items: commandRecordJsonSchema,
                description: "Optional final structured command history.",
              },
              hypotheses: {
                type: "array",
                items: hypothesisRecordJsonSchema,
                description: "Optional final structured hypotheses.",
              },
              changes: {
                type: "array",
                items: changeRecordJsonSchema,
                description: "Optional final structured changes.",
              },
              next_steps: {
                ...stringArrayJsonSchema,
                description: "Optional remaining next steps at closure time.",
              },
              closing_note: {
                type: "string",
                description:
                  "Optional closing note to append as an Execution event after the case closes.",
              },
              closing_data: {
                ...looseObjectJsonSchema,
                description: "Optional structured payload for the closing event.",
              },
            },
          },
        },
        {
          name: "enderai_request",
          description:
            "Lower-level escape hatch for HTTP requests to the EnderAI backend configured by ENDERAI_BASE_URL. Prefer the guided case tools for meaningful work; write-like calls require an active case unless you provide unsafe_write_reason.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              method: { type: "string", description: "HTTP method (GET/POST/...)." },
              path: {
                type: "string",
                description:
                  'Request path starting with "/". Example: "/api/v1/threads/".',
              },
              query: {
                type: "object",
                description: "Query string parameters (object).",
                additionalProperties: true,
              },
              headers: {
                type: "object",
                description: "Additional headers (object of strings).",
                additionalProperties: { type: "string" },
              },
              json: { description: "JSON body to send." },
              text: { type: "string", description: "Raw text body to send." },
              bearerToken: {
                type: "string",
                description:
                  "Optional per-call bearer token override. Prefer ENDERAI_BEARER_TOKEN instead.",
              },
              unsafe_write_reason: {
                type: "string",
                description:
                  "Optional explicit reason for a write-like escape-hatch request when no active case exists. Prefer enderai_begin_case for meaningful work.",
              },
              timeoutMs: {
                type: "integer",
                description: "Optional per-call timeout override (ms).",
                minimum: 1,
              },
              audit: {
                type: "object",
                description:
                  "Optional per-call audit metadata. When an Execution id is known, this server can append an Event with request/response (secrets redacted).",
                additionalProperties: false,
                properties: {
                  intent: {
                    type: "string",
                    description: "Human-readable reason for the call.",
                  },
                  run_id: {
                    type: "string",
                    description:
                      "Deprecated: use execution_id. Optional audit execution id when this MCP session is already attached to that case.",
                  },
                  execution_id: {
                    type: "string",
                    description:
                      "Optional execution id for audit events. Write-like calls still require an active case started through enderai_begin_case.",
                  },
                },
              },
            },
            required: ["method", "path"],
          },
        },
        {
          name: "enderai_begin_document",
          description:
            "Taskforce v2 document lifecycle: start of meaningful work. Lists current user's V2 documents, scores them against the request using a deterministic congruence engine (title/file/symbol/error/anchor/collaborator overlap, recency, intent phrases minus tenant/repo/error-family/terminal-state conflicts), and either reuses+self-heals the top match or creates a fresh document. Honors explicit document_id and force_new. Remembers the active document for this MCP session. Pass `usage` to report this turn's token consumption — the backend prices it and computes attributable savings (cache, summary-only, reuse-on-begin) that show up on the Taskforce Metrics page.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              request_summary: {
                type: "string",
                description: "Concise statement of the new work request or problem to investigate.",
              },
              goal: { type: "string", description: "Optional intended outcome." },
              acceptance_criteria: {
                type: "string",
                description: "Optional success criteria.",
              },
              title: { type: "string", description: "Optional preferred document title." },
              collaborators: { ...stringArrayJsonSchema, description: "Known collaborators." },
              files: { ...stringArrayJsonSchema, description: "Files or directories in scope." },
              symbols: { ...stringArrayJsonSchema, description: "Code symbols or product terms." },
              errors: { ...stringArrayJsonSchema, description: "Error strings." },
              contexts: {
                ...stringArrayJsonSchema,
                description: "Free-form context labels (tenant/customer/product hints).",
              },
              document_id: {
                type: "string",
                description: "Optional explicit document to reuse without scoring.",
              },
              reuse_within_seconds: {
                type: "integer",
                minimum: 0,
                description:
                  "Recency window (in seconds) for the recency scoring signal. Defaults to 30 days.",
              },
              force_new: {
                type: "boolean",
                description: "Skip scoring and create a fresh document.",
              },
              visibility: {
                type: "string",
                enum: ["private", "organization"],
                description:
                  "Visibility to use when creating a fresh document. Defaults to private.",
              },
              demo: {
                type: "boolean",
                description: "Operate against demo documents.",
              },
              usage: taskforceUsageJsonSchema,
            },
            required: ["request_summary"],
          },
        },
        {
          name: "enderai_update_document",
          description:
            "Append material progress to the active Taskforce v2 document and keep Summary claims backed by Details evidence anchors. Requires a prior enderai_begin_document call in this MCP session unless document_id is supplied. Use enderai_finish_document, not this tool, to finalize. Pass `usage` to report this turn's token consumption — the backend prices it and computes attributable savings (including the summary-only savings when view_consulted == 'summary') that show up on the Taskforce Metrics page.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              document_id: { type: "string", description: "Optional explicit document id." },
              title: { type: "string", description: "Corrected title." },
              description: { type: "string", description: "Corrected description." },
              human_summary: {
                type: "string",
                description:
                  "Only set when explicitly asked to edit the human summary; otherwise leave untouched.",
              },
              summary_points: {
                ...stringArrayJsonSchema,
                description: "Concise claims to append to the Summary report.",
              },
              ai_generated_summary: {
                type: "string",
                description: "Agent-maintained executive summary.",
              },
              collaborators: {
                ...stringArrayJsonSchema,
                description: "Collaborators to merge into the document.",
              },
              details_sections: {
                type: "array",
                description:
                  "Explicit Details sections to upsert by anchor_id (full replace on match).",
                items: {
                  type: "object",
                  additionalProperties: false,
                  required: ["anchor_id", "markdown"],
                  properties: {
                    anchor_id: { type: "string", minLength: 1 },
                    markdown: { type: "string" },
                  },
                },
              },
              commands: {
                type: "array",
                description: "Commands that were run, with purpose and salient result.",
                items: {
                  type: "object",
                  additionalProperties: false,
                  required: ["cmd"],
                  properties: {
                    cmd: { type: "string", minLength: 1 },
                    purpose: { type: "string" },
                    salient_result: { type: "string" },
                    ts: { type: "string" },
                  },
                },
              },
              files: { ...stringArrayJsonSchema, description: "Inspected or changed files." },
              links: { ...stringArrayJsonSchema, description: "Relevant links accessed." },
              decisions: {
                type: "array",
                description: "Decisions taken with rationale.",
                items: {
                  type: "object",
                  additionalProperties: false,
                  required: ["statement"],
                  properties: {
                    statement: { type: "string", minLength: 1 },
                    rationale: { type: "string" },
                  },
                },
              },
              changes: {
                type: "array",
                description: "Code/config/docs/test/infra changes made.",
                items: {
                  type: "object",
                  additionalProperties: false,
                  required: ["kind", "summary"],
                  properties: {
                    kind: { type: "string", minLength: 1 },
                    summary: { type: "string", minLength: 1 },
                    files: stringArrayJsonSchema,
                  },
                },
              },
              open_questions: { ...stringArrayJsonSchema, description: "Unresolved items." },
              progress_note: { type: "string", description: "Human-readable update." },
              visibility: {
                type: "string",
                enum: ["private", "organization"],
                description:
                  "Optional visibility change. Only the document owner can change visibility.",
              },
              demo: { type: "boolean" },
              usage: taskforceUsageJsonSchema,
            },
          },
        },
        {
          name: "enderai_finish_document",
          description:
            "Finalize the active Taskforce v2 document at completion or pause. Adds an Outcome section to Details (with status, outcome, validation, follow-ups) and links it from Summary. Clears the active-document pointer for this MCP session. Pass `usage` to report the finalization turn's token consumption — the backend prices it and computes attributable savings that show up on the Taskforce Metrics page.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              document_id: { type: "string", description: "Optional explicit document id." },
              outcome: { type: "string", description: "Final result." },
              validation: { ...stringArrayJsonSchema, description: "Checks performed and results." },
              follow_ups: { ...stringArrayJsonSchema, description: "Remaining work." },
              status: {
                type: "string",
                enum: ["done", "paused", "blocked", "superseded"],
                description: "Completion status (defaults to done).",
              },
              closing_note: { type: "string", description: "Optional final narrative." },
              demo: { type: "boolean" },
              usage: taskforceUsageJsonSchema,
            },
          },
        },
        {
          name: "enderai_session_info",
          description:
            "Return the current EnderAI MCP session policy, auth model, active case/topic ids, and authenticated user summary when available.",
          inputSchema: { type: "object", additionalProperties: false, properties: {} },
        },
        {
          name: "enderai_openapi",
          description: "Fetch the backend OpenAPI JSON at /api/v1/openapi.json.",
          inputSchema: { type: "object", additionalProperties: false, properties: {} },
        },
        {
          name: "enderai_health_check",
          description: "Fetch the backend health check at /api/v1/utils/health-check/.",
          inputSchema: { type: "object", additionalProperties: false, properties: {} },
        },
      ],
    };
  });

  server.setRequestHandler(CallToolRequestSchema, async (req) => {
    const name = req.params.name;

    try {
      if (name === "enderai_begin_case") {
        const args = BeginCaseArgsSchema.parse(req.params.arguments ?? {});
        const bearerToken = opts.backendBearerTokenProvider?.();
        await reconcileActiveCaseContext({ bearerToken });
        if (auditState.executionId) {
          return toolError(
            `A case is already active in this MCP session (${auditState.executionId}). Run enderai_finish_case before beginning a new one.`,
          );
        }

        const requestSummary = trimToUndefined(args.request_summary)!;
        const caseTitle = trimToUndefined(args.case_title);
        const topicTitle = trimToMaxLength(
          trimToUndefined(args.topic_title) ??
          (trimToUndefined(args.workflow_key)
            ? humanizeWorkflowKey(trimToUndefined(args.workflow_key)!)
            : caseTitle ?? requestSummary),
          DEFAULT_THREAD_TITLE_MAX_CHARS,
        );
        const workflowKey =
          trimToUndefined(args.workflow_key) ??
          slugifyWorkflowKey(topicTitle);
        const reuseWithinSeconds =
          args.reuse_within_seconds ?? DEFAULT_REUSE_WINDOW_SECONDS;
        const minimumMatchConfidence: "medium" = "medium";
        const topicLookupRes = await enderaiFetch({
          method: "GET",
          path: "/api/v1/topics/",
          bearerToken,
          query: {
            workflow_key: workflowKey,
            limit: 1,
          },
        });
        if (!topicLookupRes.ok) {
          throw new Error(
            `enderai_begin_case failed to look up the topic: ${extractErrorDetail(topicLookupRes)} (status ${topicLookupRes.status}).`,
          );
        }

        const existingTopic = Array.isArray(asRecord(topicLookupRes.data).data)
          ? (asRecord(topicLookupRes.data).data as unknown[])
              .map((topic) => asRecord(topic))
              .find((topic) => typeof topic.id === "string")
          : undefined;
        let matchedTopic: Record<string, any> | undefined;
        if (!existingTopic) {
          const topicMatchRes = await enderaiFetch({
            method: "POST",
            path: "/api/v1/topics/match",
            bearerToken,
            json: {
              ...buildTopicMatchPayload(args, requestSummary, caseTitle),
              limit: 3,
            },
          });
          if (!topicMatchRes.ok) {
            throw new Error(
              `enderai_begin_case failed to match existing topics: ${extractErrorDetail(topicMatchRes)} (status ${topicMatchRes.status}).`,
            );
          }
          matchedTopic = selectReusableMatchedTopic(
            topicMatchRes.data,
            minimumMatchConfidence,
            reuseWithinSeconds,
          );
        }

        let topicData = existingTopic ?? matchedTopic;
        if (!topicData) {
          const topicRes = await enderaiFetch({
            method: "POST",
            path: "/api/v1/topics/",
            bearerToken,
            json: pruneUndefined({
              title: topicTitle,
              workflow_key: workflowKey,
              aliases: args.aliases ?? [],
            }),
          });
          if (!topicRes.ok) {
            throw new Error(
              `enderai_begin_case failed to create the topic: ${extractErrorDetail(topicRes)} (status ${topicRes.status}).`,
            );
          }
          topicData = asRecord(topicRes.data);
        }

        const topicId = typeof topicData.id === "string" ? topicData.id : undefined;
        if (!topicId) {
          throw new Error(
            "enderai_begin_case did not receive a topic id from /api/v1/topics/.",
          );
        }

        let contextPack: unknown | null = null;
        if (args.auto_hydrate !== false) {
          const contextPackRes = await enderaiFetch({
            method: "POST",
            path: "/api/v1/context-packs/build",
            bearerToken,
            json: pruneUndefined({
              topic_id: topicId,
              title: caseTitle ?? requestSummary,
              request_summary: requestSummary,
              aliases: args.aliases,
              files: args.files,
              symbols: args.symbols,
              errors: args.errors,
              symptoms: args.symptoms,
              contexts: collectContextHints(args),
              max_cases_per_topic:
                args.max_cases_per_topic ?? DEFAULT_CONTEXT_PACK_CASE_LIMIT,
            }),
          });
          if (!contextPackRes.ok) {
            throw new Error(
              `enderai_begin_case failed to build a ContextPack: ${extractErrorDetail(contextPackRes)} (status ${contextPackRes.status}).`,
            );
          }
          contextPack = contextPackRes.data;
        }

        const contextPackRecord = asRecord(contextPack);
        const caseCreate = pruneUndefined({
          topic_id: topicId,
          title: caseTitle,
          status: "running",
          input_summary: requestSummary,
          summary_current: requestSummary,
          files: args.files ?? [],
          symbols: args.symbols ?? [],
          errors: args.errors ?? [],
          symptoms: args.symptoms ?? [],
          context_pack_snapshot: contextPackRecord.context_pack_snapshot,
        });
        const caseRes = await enderaiFetch({
          method: "POST",
          path: "/api/v1/cases/",
          bearerToken,
          json: caseCreate,
        });
        if (!caseRes.ok) {
          throw new Error(
            `enderai_begin_case failed to create the case: ${extractErrorDetail(caseRes)} (status ${caseRes.status}).`,
          );
        }

        const contextPackSnapshot = asRecord(contextPackRecord.context_pack_snapshot);
        const relevantCases = Array.isArray(contextPackRecord.relevant_cases)
          ? contextPackRecord.relevant_cases
          : Array.isArray(contextPackSnapshot.relevant_cases)
            ? contextPackSnapshot.relevant_cases
            : [];
        const caseData = asRecord(caseRes.data);
        const caseId = typeof caseData.id === "string" ? caseData.id : undefined;
        if (!caseId) {
          throw new Error(
            "enderai_begin_case did not receive a case id from /api/v1/cases/.",
          );
        }
        setActiveCaseContext(caseId, topicId);
        const skillHydration =
          args.auto_hydrate === false
            ? {
                status: "skipped",
                reason: "auto_hydrate was false.",
                local_skill_sync: {
                  directory: getLocalSkillsDirectory(),
                  index_path: null,
                  local_skill_files: [],
                  agent_instructions: [
                    "Skill sync was skipped because auto_hydrate was false. Run enderai_use_skill after beginning the case if skill guidance is needed.",
                  ],
                },
              }
            : await tryHydrateSkillsForCase({ bearerToken, caseData });
        const skillHydrationRecord = asRecord(skillHydration);
        const localSkillSyncRecord = asRecord(skillHydrationRecord.local_skill_sync);
        const localSkillFiles = Array.isArray(localSkillSyncRecord.local_skill_files)
          ? localSkillSyncRecord.local_skill_files
          : [];
        const result = {
          policy_version: POLICY_VERSION,
          workflow_model: WORKFLOW_MODEL,
          auth_model: AUTH_MODEL,
          topic: topicData,
          case: caseRes.data,
          context_pack: contextPack,
          skill_hydration: skillHydration,
          hydration: {
            auto_hydrate_requested: args.auto_hydrate !== false,
            hydration_status: args.auto_hydrate === false ? "skipped" : "attached",
            context_pack_attached: Boolean(contextPackRecord.context_pack_snapshot),
            skill_hydration_status:
              typeof skillHydrationRecord.status === "string"
                ? skillHydrationRecord.status
                : "unknown",
            local_skill_file_count: localSkillFiles.length,
            matched_topic_id:
              typeof contextPackSnapshot.topic_id === "string"
                ? contextPackSnapshot.topic_id
                : topicId,
            relevant_case_count: relevantCases.length,
            context_found:
              Boolean(contextPackRecord.context_pack_snapshot) || relevantCases.length > 0,
          },
          reused_topic: Boolean(existingTopic || matchedTopic),
          next: {
            use_skill_tool: "enderai_use_skill",
            local_skills_dir: getLocalSkillsDirectory(),
            update_tool: "enderai_update_case",
            finish_tool: "enderai_finish_case",
            case_id: caseId,
            topic_id: topicId,
          },
        };
        await auditWorkflowTool({
          bearerToken,
          executionId: caseId,
          message: "Begin case",
          tool: "enderai_begin_case",
          request: args,
          response: result,
        });
        return toolJson(result);
      }

      if (name === "enderai_update_case") {
        const args = UpdateCaseArgsSchema.parse(req.params.arguments ?? {});
        const bearerToken = opts.backendBearerTokenProvider?.();
        const caseId = await resolveCaseId(args.case_id, "enderai_update_case", bearerToken);

        const casePatch = pruneUndefined({
          title: trimToUndefined(args.title),
          input_summary: trimToUndefined(args.input_summary),
          summary_current: trimToUndefined(args.summary_current),
          files: args.files,
          symbols: args.symbols,
          errors: args.errors,
          symptoms: args.symptoms,
          commands: args.commands,
          hypotheses: args.hypotheses,
          changes: args.changes,
          outcome: trimToUndefined(args.outcome),
          next_steps: args.next_steps,
        });
        const needsPatch = Object.keys(casePatch).length > 0;
        const caseRes = await enderaiFetch({
          method: needsPatch ? "PATCH" : "GET",
          path: `/api/v1/cases/${caseId}`,
          bearerToken,
          ...(needsPatch ? { json: casePatch } : {}),
        });
        if (!caseRes.ok) {
          throw new Error(
            `enderai_update_case failed: ${extractErrorDetail(caseRes)} (status ${caseRes.status}).`,
          );
        }

        const caseData = asRecord(caseRes.data);
        setActiveCaseContext(
          caseId,
          typeof caseData.topic_id === "string" ? caseData.topic_id : auditState.threadId,
        );

        let progressEvent: unknown | null = null;
        if (args.progress_note) {
          const progressRes = await createExecutionEvent({
            bearerToken,
            caseId,
            type: "mcp_progress",
            message: args.progress_note,
            data: pruneUndefined({
              ...(args.progress_data ?? {}),
              changed_fields: Object.keys(casePatch),
            }),
          });
          if (!progressRes.ok) {
            throw new Error(
              `enderai_update_case failed to append the progress event: ${extractErrorDetail(progressRes)} (status ${progressRes.status}).`,
            );
          }
          progressEvent = progressRes.data;
        }

        const result = {
          case: caseRes.data,
          progress_event: progressEvent,
          next: {
            finish_tool: "enderai_finish_case",
            case_id: caseId,
            topic_id: caseData.topic_id ?? auditState.threadId ?? null,
          },
        };
        await auditWorkflowTool({
          bearerToken,
          executionId: caseId,
          message: "Update case",
          tool: "enderai_update_case",
          request: args,
          response: result,
        });
        return toolJson(result);
      }

      if (name === "enderai_use_skill") {
        const args = UseSkillArgsSchema.parse(req.params.arguments ?? {});
        const bearerToken = opts.backendBearerTokenProvider?.();
        const activeContext = await reconcileActiveCaseContext({ bearerToken });

        if (
          args.case_id &&
          activeContext.caseId &&
          activeContext.caseId !== args.case_id
        ) {
          return toolError(
            `enderai_use_skill is currently attached to case ${activeContext.caseId}. Run enderai_finish_case before switching to case ${args.case_id}.`,
          );
        }

        let caseData = activeContext.caseData;
        const caseId = args.case_id ?? activeContext.caseId ?? undefined;
        if (caseId && (!caseData || caseData.id !== caseId)) {
          const caseRes = await enderaiFetch({
            method: "GET",
            path: `/api/v1/cases/${caseId}`,
            bearerToken,
            query: args.demo ? { demo: true } : undefined,
          });
          if (!caseRes.ok) {
            throw new Error(
              `enderai_use_skill failed to read the case: ${extractErrorDetail(caseRes)} (status ${caseRes.status}).`,
            );
          }
          caseData = asRecord(caseRes.data);
          const topicId =
            typeof caseData.topic_id === "string" ? caseData.topic_id : undefined;
          setActiveCaseContext(caseId, topicId);
        }

        const payload = buildUseSkillPayload(args, caseData);
        if (!hasSkillMatchSignals(payload)) {
          return toolError(
            "enderai_use_skill requires an active case, case_id, skill_id, or request signals to match a generated Skill.",
          );
        }

        const skillRes = await enderaiFetch({
          method: "POST",
          path: "/api/v1/skills/use",
          bearerToken,
          query: args.demo ? { demo: true } : undefined,
          json: payload,
        });
        if (!skillRes.ok) {
          throw new Error(
            `enderai_use_skill failed: ${extractErrorDetail(skillRes)} (status ${skillRes.status}).`,
          );
        }
        const localSkillSync = await syncSkillUseResultToLocalFiles(skillRes.data);

        const result = {
          skill_use: skillRes.data,
          local_skill_sync: localSkillSync,
          case: caseData,
          next: {
            update_tool: "enderai_update_case",
            finish_tool: "enderai_finish_case",
            case_id: caseId ?? null,
            local_skills_dir: localSkillSync.directory,
            topic_id:
              typeof caseData?.topic_id === "string"
                ? caseData.topic_id
                : auditState.threadId ?? null,
          },
        };
        await auditWorkflowTool({
          bearerToken,
          executionId: caseId,
          message: "Use generated skill",
          tool: "enderai_use_skill",
          request: args,
          response: result,
        });
        return toolJson(result);
      }

      if (name === "enderai_finish_case") {
        const args = FinishCaseArgsSchema.parse(req.params.arguments ?? {});
        const status = trimToUndefined(args.status) ?? "done";
        if (!isTerminalCaseStatus(status)) {
          return toolError(
            "enderai_finish_case requires a terminal status such as done, completed, closed, aborted, or failed.",
          );
        }

        const bearerToken = opts.backendBearerTokenProvider?.();
        const caseId = await resolveCaseId(args.case_id, "enderai_finish_case", bearerToken);
        const casePatch = pruneUndefined({
          status,
          summary_current: trimToUndefined(args.summary_current),
          outcome: trimToUndefined(args.outcome),
          files: args.files,
          symbols: args.symbols,
          errors: args.errors,
          symptoms: args.symptoms,
          commands: args.commands,
          hypotheses: args.hypotheses,
          changes: args.changes,
          next_steps: args.next_steps,
        });

        const caseRes = await enderaiFetch({
          method: "PATCH",
          path: `/api/v1/cases/${caseId}`,
          bearerToken,
          json: casePatch,
        });
        if (!caseRes.ok) {
          throw new Error(
            `enderai_finish_case failed: ${extractErrorDetail(caseRes)} (status ${caseRes.status}).`,
          );
        }

        const caseData = asRecord(caseRes.data);
        setActiveCaseContext(
          caseId,
          typeof caseData.topic_id === "string" ? caseData.topic_id : auditState.threadId,
        );
        const shouldClearContext = isClosedCaseRecord(caseData);

        try {
          let closingEvent: unknown | null = null;
          if (args.closing_note) {
            const closingRes = await createExecutionEvent({
              bearerToken,
              caseId,
              type: "mcp_finish",
              message: args.closing_note,
              data: args.closing_data ?? {},
            });
            if (!closingRes.ok) {
              throw new Error(
                `enderai_finish_case failed to append the closing event: ${extractErrorDetail(closingRes)} (status ${closingRes.status}).`,
              );
            }
            closingEvent = closingRes.data;
          }

          const result = {
            case: caseRes.data,
            closing_event: closingEvent,
            session_context_cleared: true,
            next: {
              begin_tool: "enderai_begin_case",
              topic_id: caseData.topic_id ?? auditState.threadId ?? null,
            },
          };
          await auditWorkflowTool({
            bearerToken,
            executionId: caseId,
            message: "Finish case",
            tool: "enderai_finish_case",
            request: args,
            response: result,
          });
          return toolJson(result);
        } finally {
          if (shouldClearContext) clearActiveCaseContext();
        }
      }

      if (name === "enderai_begin_document") {
        const args = BeginDocumentArgsSchema.parse(req.params.arguments ?? {});
        const bearerToken = opts.backendBearerTokenProvider?.();
        try {
          const result = await beginDocument(args, {
            bearerToken,
            state: activeDocumentState,
          });
          return toolJson(result);
        } catch (err) {
          return toolError(
            `enderai_begin_document failed: ${err instanceof Error ? err.message : String(err)}`,
          );
        }
      }

      if (name === "enderai_update_document") {
        const args = UpdateDocumentArgsSchema.parse(req.params.arguments ?? {});
        const bearerToken = opts.backendBearerTokenProvider?.();
        try {
          const result = await updateDocument(args, {
            bearerToken,
            state: activeDocumentState,
          });
          return toolJson(result);
        } catch (err) {
          return toolError(
            `enderai_update_document failed: ${err instanceof Error ? err.message : String(err)}`,
          );
        }
      }

      if (name === "enderai_finish_document") {
        const args = FinishDocumentArgsSchema.parse(req.params.arguments ?? {});
        const bearerToken = opts.backendBearerTokenProvider?.();
        try {
          const result = await finishDocument(args, {
            bearerToken,
            state: activeDocumentState,
          });
          return toolJson(result);
        } catch (err) {
          return toolError(
            `enderai_finish_document failed: ${err instanceof Error ? err.message : String(err)}`,
          );
        }
      }

      if (name === "enderai_request") {
        const args = EnderaiRequestArgsSchema.parse(req.params.arguments ?? {});
        const { audit, ...reqArgs } = args;
        const method = args.method.toUpperCase();
        const sessionToken = opts.backendBearerTokenProvider?.();
        const bearerToken = reqArgs.bearerToken ?? sessionToken;
        const requestedAuditExecutionId = audit?.execution_id ?? audit?.run_id;
        const auditExecutionId = auditState.executionId;
        const auditIntent = audit?.intent;
        const unsafeWriteReason = trimToUndefined(args.unsafe_write_reason);

        if (
          requestedAuditExecutionId &&
          auditExecutionId &&
          requestedAuditExecutionId !== auditExecutionId
        ) {
          return toolError(
            `enderai_request is currently attached to case ${auditExecutionId}. Run enderai_finish_case before switching to case ${requestedAuditExecutionId}.`,
          );
        }

        if (
          isWriteLikeMethod(method) &&
          !auditExecutionId &&
          !unsafeWriteReason
        ) {
          return toolError(
            "enderai_request write-like calls require an active case. Run enderai_begin_case first so EnderAI can auto-hydrate relevant context; audit.execution_id does not replace an active case. You can also provide unsafe_write_reason for an explicit escape hatch.",
          );
        }

        const rewrite = rewriteDeprecatedApiPath(reqArgs.path);
        const effectivePath = rewrite.path;
        const normalizedJson = normalizeJsonArgument(reqArgs.json);
        const res = await enderaiFetch({
          ...reqArgs,
          path: effectivePath,
          bearerToken,
          json: normalizedJson,
        });

        const isExecutionStart =
          method === "POST" &&
          effectivePath.replace(/\/+$/, "") === "/api/v1/executions/start";
        if (isExecutionStart && res.ok) {
          const ids = extractExecutionStartIds(res.data);
          setActiveCaseContext(ids.executionId, ids.threadId);
        }

        const auto: Record<string, unknown> = {};
        if (rewrite.rewrites.length > 0) auto.path_rewrite = rewrite.rewrites;

        const normalizedPath = effectivePath.replace(/\/+$/, "");
        const isArtifactCreate =
          method === "POST" &&
          normalizedPath === "/api/v1/artifacts";
        if (isArtifactCreate && res.ok) {
          const data = asRecord(res.data);
          const artifactId =
            typeof data.id === "string" ? data.id : undefined;
          const createdAt =
            typeof data.created_at === "string" ? data.created_at : null;
          const linkRes = await tryAutoLinkLibraryItem({
            bearerToken,
            executionId: auditExecutionId ?? auditState.executionId,
            artifactId,
            createdAt,
          });
          if (linkRes) auto.artifact_link = capJson(redactSecrets(linkRes));
        }

        const auditData = capJson(
          redactSecrets({
            tool: "enderai_request",
            intent: auditIntent ?? null,
            request: {
              method: args.method,
              path_original: args.path,
              path: effectivePath,
              query: args.query,
              headers: args.headers,
              json: args.json,
              text: args.text,
              unsafe_write_reason: args.unsafe_write_reason,
              timeoutMs: args.timeoutMs,
            },
            response: res,
            auto,
            execution_context: {
              execution_id: auditExecutionId ?? auditState.executionId ?? null,
              thread_id: auditState.threadId ?? null,
            },
          }),
        );
        const message =
          auditIntent?.trim() ||
          `${args.method.toUpperCase()} ${effectivePath}${
            effectivePath === args.path ? "" : " (rewritten)"
          }`;
        await tryCreateRunEvent({
          bearerToken,
          executionId: auditExecutionId ?? auditState.executionId,
          type: "mcp",
          message,
          data: auditData,
        });

        return toolJson(res);
      }

      if (name === "enderai_session_info") {
        const bearerToken =
          opts.backendBearerTokenProvider?.() ?? loadConfig().bearerToken;
        await reconcileActiveCaseContext({ bearerToken });
        let user: Record<string, unknown> | null = null;

        if (bearerToken) {
          const meRes = await enderaiFetch({
            method: "GET",
            path: "/api/v1/users/me",
            bearerToken,
          });
          if (meRes.ok) {
            const me = asRecord(meRes.data);
            user = {
              id: typeof me.id === "string" ? me.id : null,
              email: typeof me.email === "string" ? me.email : null,
              full_name: typeof me.full_name === "string" ? me.full_name : null,
            };
          } else {
            user = {
              unavailable: true,
              status: meRes.status,
              detail: extractErrorDetail(meRes),
            };
          }
        }

        return toolJson({
          policy_version: POLICY_VERSION,
          workflow_model: WORKFLOW_MODEL,
          auth_model: AUTH_MODEL,
          user,
          active_case_id: auditState.executionId ?? null,
          active_topic_id: auditState.threadId ?? null,
          active_document: activeDocumentState.documentId
            ? {
                id: activeDocumentState.documentId,
                title: activeDocumentState.title ?? null,
                started_at: activeDocumentState.startedAt ?? null,
                last_updated_at: activeDocumentState.lastUpdatedAt ?? null,
                demo: activeDocumentState.demo ?? false,
              }
            : null,
          local_skills_dir: getLocalSkillsDirectory(),
          skills_discovery:
            "enderai_begin_case and enderai_use_skill sync matched EnderAI Skills as markdown files under local_skills_dir. Read the returned local_skill_files before applying skill guidance.",
          session_ready: Boolean(bearerToken),
          next: {
            begin_tool: "enderai_begin_case",
            use_skill_tool: "enderai_use_skill",
            update_tool: "enderai_update_case",
            finish_tool: "enderai_finish_case",
            v2_begin_tool: "enderai_begin_document",
            v2_update_tool: "enderai_update_document",
            v2_finish_tool: "enderai_finish_document",
          },
        });
      }

      if (name === "enderai_openapi") {
        return await runSimpleGetTool({
          name: "enderai_openapi",
          path: "/api/v1/openapi.json",
          message: "Fetch OpenAPI schema",
        });
      }

      if (name === "enderai_health_check") {
        return await runSimpleGetTool({
          name: "enderai_health_check",
          path: "/api/v1/utils/health-check/",
          message: "Health check",
        });
      }

      return toolError(`Unknown tool: ${name}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return toolError(msg);
    }
  });

  return server;
}
