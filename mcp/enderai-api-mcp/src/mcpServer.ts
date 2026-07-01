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
  beginDocument,
  createActiveDocumentState,
  finishDocument,
  updateDocument,
  type ActiveDocumentState,
} from "./v2Documents/index.js";
import { callTaskforceDiscover } from "./taskforce/discover.js";
import {
  callTaskforceSessionObserve,
  callTaskforceSessionStart,
} from "./taskforce/session.js";
import { callTaskforceSessionLog } from "./taskforce/sessionLog.js";

export type McpServerOptions = {
  // Optional backend bearer token provider used for all tool calls in this server instance.
  // This enables a hosted MCP server to act per user by binding the validated MCP token
  // to a session while still supporting token rotation during that session.
  backendBearerTokenProvider?: () => string | undefined;
  // TF-203 / C4: self-reported harness/client (e.g. "claude-code", "codex",
  // "cursor"). Stamped onto discover / session_start / session_observe calls so
  // cross-boundary reuse (TF-202 / C3) can attribute the origin + consuming
  // tool. A per-call `client` arg always wins; this is the server-wide default
  // for a harness that mounts one MCP instance (Claude Code via the skill).
  // Advisory provenance only — identity stays the bearer token. Defaults to
  // TASKFORCE_CLIENT / ENDERAI_CLIENT env when unset.
  defaultClient?: string;
};

function resolveDefaultClient(opts: McpServerOptions): string | undefined {
  return (
    opts.defaultClient?.trim() ||
    process.env.TASKFORCE_CLIENT?.trim() ||
    process.env.ENDERAI_CLIENT?.trim() ||
    undefined
  );
}

const AUDIT_MAX_BYTES = 48_000;
const AUDIT_PREVIEW_CHARS = 8_000;
const POLICY_VERSION = "topic_case_v1";
const WORKFLOW_MODEL = "topic_case_v1";
const AUTH_MODEL = "single_token_hosted_mcp";

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

const TaskforceUsageSchema = z
  .object({
    model_id: z.string().min(1),
    input_tokens: z.number().int().nonnegative().optional(),
    output_tokens: z.number().int().nonnegative().optional(),
    cache_read_input_tokens: z.number().int().nonnegative().optional(),
    cache_creation_input_tokens: z.number().int().nonnegative().optional(),
    view_consulted: z.enum(["summary", "details", "both"]).optional(),
    occurred_at: z.string().optional(),
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
    usage: TaskforceUsageSchema.optional(),
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
    usage: TaskforceUsageSchema.optional(),
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
    usage: TaskforceUsageSchema.optional(),
  })
  .strict();

// TF-175 / Phase 1: hook-driven discovery. The MCP tool here is mostly a
// fallback for harnesses without hook support — the canonical caller is
// the UserPromptSubmit hook (TF-176) that POSTs the backend directly.
const TaskforceDiscoverArgsSchema = z
  .object({
    prompt: z.string().min(1).max(8000),
    cwd: z.string().optional(),
    files: z.array(z.string()).optional(),
    git_branch: z.string().optional(),
    recent_commands: z.array(z.string()).optional(),
    k: z.number().int().min(1).max(3).optional(),
    min_score: z.number().min(0).max(1).optional(),
    session_id: z.string().min(1).max(128).optional(),
    // TF-203 / C4: self-reported harness, advisory provenance.
    client: z.string().min(1).max(32).optional(),
    demo: z.boolean().optional(),
  })
  .strict();

// TF-176 / Phase 2: per-session consult log.
const TaskforceSessionLogArgsSchema = z
  .object({
    session_id: z.string().min(1).max(128),
    limit: z.number().int().min(1).max(200).optional(),
  })
  .strict();

// TF-181 / Phase 7: Tier 2 hookless-agent entry points.
const TaskforceSessionStartArgsSchema = z
  .object({
    prompt: z.string().min(1).max(8000),
    cwd: z.string().optional(),
    files: z.array(z.string()).optional(),
    git_branch: z.string().optional(),
    recent_commands: z.array(z.string()).optional(),
    k: z.number().int().min(1).max(3).optional(),
    min_score: z.number().min(0).max(1).optional(),
    // TF-203 / C4: self-reported harness, advisory provenance.
    client: z.string().min(1).max(32).optional(),
    demo: z.boolean().optional(),
  })
  .strict();

const TaskforceTranscriptTurnSchema = z
  .object({ role: z.string().min(1), content: z.string() })
  .strict();

const TaskforceCommandRunSchema = z
  .object({
    cmd: z.string().min(1).max(2000),
    exit_code: z.number().int().nullable().optional(),
  })
  .strict();

const TaskforceHarnessUsageSchema = z
  .object({
    model_id: z.string().min(1).max(128),
    total_input_tokens: z.number().int().nonnegative().optional(),
    total_output_tokens: z.number().int().nonnegative().optional(),
    total_cache_read_tokens: z.number().int().nonnegative().optional(),
    total_cache_write_tokens: z.number().int().nonnegative().optional(),
  })
  .strict();

const TaskforceDetailsSectionInputSchema = z
  .object({
    anchor_id: z.string().min(1).max(64),
    markdown: z.string().min(1).max(4000),
  })
  .strict();

const TaskforceSessionObserveArgsSchema = z
  .object({
    session_id: z.string().min(1).max(128),
    kind: z.enum(["checkpoint", "final"]),
    prompt: z.string().max(8000).optional(),
    active_document_id: z.string().uuid().optional(),
    visibility: z.enum(["private", "organization"]).optional(),
    // TF-203 / C4: self-reported harness, advisory provenance.
    client: z.string().min(1).max(32).optional(),
    transcript: z.array(TaskforceTranscriptTurnSchema).optional(),
    cwd: z.string().optional(),
    files_touched: z.array(z.string()).optional(),
    commands_run: z.array(TaskforceCommandRunSchema).optional(),
    diff_summary: z.string().optional(),
    duration_ms: z.number().int().nonnegative().optional(),
    harness: TaskforceHarnessUsageSchema.optional(),
    checkpoint_index: z.number().int().positive().optional(),
    summary_points: z.array(z.string().min(1)).optional(),
    details_sections: z.array(TaskforceDetailsSectionInputSchema).optional(),
    decisions: z.array(z.string().min(1)).optional(),
    outcome: z.enum(["shipped", "blocked", "paused", "interrupted"]).optional(),
  })
  .strict();

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

function asRecord(value: unknown): Record<string, any> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, any>;
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

  // TF-180: every `enderai_*` tool has a `taskforce_*` canonical alias.
  // The dispatcher below normalizes `taskforce_*` → `enderai_*` so handlers
  // stay coded against the existing names. Both names are advertised in
  // ListTools so existing user configs keep working while new docs +
  // CLAUDE.md can point at the canonical taskforce_* names.
  const TASKFORCE_TO_ENDERAI_ALIASES: Record<string, string> = {
    taskforce_request: "enderai_request",
    taskforce_begin_document: "enderai_begin_document",
    taskforce_update_document: "enderai_update_document",
    taskforce_finish_document: "enderai_finish_document",
    taskforce_session_info: "enderai_session_info",
    taskforce_openapi: "enderai_openapi",
    taskforce_health_check: "enderai_health_check",
  };
  const ENDERAI_TO_TASKFORCE_NAMES: Record<string, string> = Object.fromEntries(
    Object.entries(TASKFORCE_TO_ENDERAI_ALIASES).map(([tf, en]) => [en, tf]),
  );
  const ALIAS_DEPRECATION_PREFIX =
    "[Deprecated alias — use the `taskforce_*` name. Removal in a future release.] ";

  server.setRequestHandler(ListToolsRequestSchema, async () => {
    const primary = [
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
                  "Optional explicit reason for a write-like escape-hatch request when no active document exists. Prefer enderai_begin_document for meaningful work.",
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
                      "Deprecated: use execution_id. Optional audit execution id when this MCP session is already attached to that execution.",
                  },
                  execution_id: {
                    type: "string",
                    description:
                      "Optional execution id for audit events. Write-like calls still require an active document started through enderai_begin_document.",
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
            "[DEPRECATED — Taskforce hooks handle this automatically. Prefer the UserPromptSubmit hook (TF-176) for discovery and the Stop hook (TF-178) for lifecycle. Use `taskforce_discover` if you need an explicit handle from within an MCP session. This tool will be removed in a future release.] Taskforce v2 document lifecycle: start of meaningful work. Lists current user's V2 documents, scores them against the request using a deterministic congruence engine (title/file/symbol/error/anchor/collaborator overlap, recency, intent phrases minus tenant/repo/error-family/terminal-state conflicts), and either reuses+self-heals the top match or creates a fresh document. Honors explicit document_id and force_new. Remembers the active document for this MCP session. Pass `usage` to report this turn's token consumption — the backend prices it and computes attributable savings (cache, summary-only, reuse-on-begin) that show up on the Taskforce Metrics page.",
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
            "[DEPRECATED — Taskforce hooks (TF-176 / TF-178) handle this automatically via the PostToolUse + Stop observe path. This tool will be removed in a future release.] Append material progress to the active Taskforce v2 document and keep Summary claims backed by Details evidence anchors. Requires a prior enderai_begin_document call in this MCP session unless document_id is supplied. Use enderai_finish_document, not this tool, to finalize. Pass `usage` to report this turn's token consumption — the backend prices it and computes attributable savings (including the summary-only savings when view_consulted == 'summary') that show up on the Taskforce Metrics page.",
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
            "[DEPRECATED — Taskforce hooks (TF-178) finalize automatically when the Claude Code session ends via the Stop hook. This tool will be removed in a future release.] Finalize the active Taskforce v2 document at completion or pause. Adds an Outcome section to Details (with status, outcome, validation, follow-ups) and links it from Summary. Clears the active-document pointer for this MCP session. Pass `usage` to report the finalization turn's token consumption — the backend prices it and computes attributable savings that show up on the Taskforce Metrics page.",
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
          name: "taskforce_session_start",
          description:
            "Canonical entry point for hookless agents (Codex, Cursor, plain API harnesses — TF-174 §15 Tier 2). Mints a UUID `session_id`, runs Taskforce discovery against the actor's library, and returns up to 3 related prior documents plus an optional `suggested_pin` when the top match is high-confidence. Thread the returned `session_id` through every subsequent `taskforce_session_observe` call. This tool **replaces** the legacy `enderai_begin_document` workflow for non-hook agents — call it once at the start of meaningful work and you do not need to call `enderai_update_document` / `enderai_finish_document` at all.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              prompt: {
                type: "string",
                minLength: 1,
                maxLength: 8000,
                description: "The user's request that initiates this session.",
              },
              cwd: { type: "string", description: "Working directory hint." },
              files: {
                ...stringArrayJsonSchema,
                description: "Files in scope for this turn.",
              },
              git_branch: { type: "string", description: "Active git branch." },
              recent_commands: {
                ...stringArrayJsonSchema,
                description: "Recent shell commands the harness knows about.",
              },
              k: {
                type: "integer",
                minimum: 1,
                maximum: 3,
                description: "Max matches to return (hard cap 3, defaults to 3).",
              },
              min_score: {
                type: "number",
                minimum: 0,
                maximum: 1,
                description: "Filter matches below this score (default 0.3).",
              },
              client: {
                type: "string",
                maxLength: 32,
                description:
                  "Self-reported harness (e.g. 'claude-code', 'codex', 'cursor'). Advisory provenance — drives cross-boundary reuse attribution (TF-202/C3). Identity stays the bearer token.",
              },
              demo: {
                type: "boolean",
                description: "Operate against demo documents.",
              },
            },
            required: ["prompt"],
          },
        },
        {
          name: "taskforce_session_observe",
          description:
            "Pair of `taskforce_session_start` (TF-174 §15 Tier 2). Call once when meaningful work completes or pauses with `kind: \"final\"`, or mid-session with `kind: \"checkpoint\"`. Pass the session_id from `taskforce_session_start`. **Prefer structured fields** (`summary_points` + `details_sections` + `decisions` + `outcome`) over shipping a transcript blob — when structured fields are present the backend skips the haiku summarizer entirely (cheaper, deterministic). Use `active_document_id` to bind the patch to the agent's chosen doc (usually the `suggested_pin` from session_start).",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              session_id: {
                type: "string",
                minLength: 1,
                maxLength: 128,
                description: "Session id from taskforce_session_start.",
              },
              kind: {
                type: "string",
                enum: ["checkpoint", "final"],
                description: "`final` at session end; `checkpoint` for mid-session updates.",
              },
              prompt: {
                type: "string",
                maxLength: 8000,
                description: "Optional context (original user request).",
              },
              active_document_id: {
                type: "string",
                description: "Document to patch; usually `suggested_pin` from session_start.",
              },
              visibility: {
                type: "string",
                enum: ["private", "organization"],
                description:
                  "Visibility for a newly created observed document. Defaults to private; use organization for shared proof runs.",
              },
              client: {
                type: "string",
                maxLength: 32,
                description:
                  "Self-reported harness (e.g. 'claude-code', 'codex', 'cursor'). Stamped as produced_by_client on a newly captured document. Advisory provenance (TF-202/C3); identity stays the bearer token.",
              },
              summary_points: {
                ...stringArrayJsonSchema,
                description: "1–6 claim sentences to append to the doc's Summary.",
              },
              details_sections: {
                type: "array",
                description: "Markdown sections to upsert by anchor_id.",
                items: {
                  type: "object",
                  additionalProperties: false,
                  required: ["anchor_id", "markdown"],
                  properties: {
                    anchor_id: { type: "string", minLength: 1, maxLength: 64 },
                    markdown: { type: "string", minLength: 1, maxLength: 4000 },
                  },
                },
              },
              decisions: {
                ...stringArrayJsonSchema,
                description: "Decisions the agent made this session.",
              },
              outcome: {
                type: "string",
                enum: ["shipped", "blocked", "paused", "interrupted"],
                description: "Terminal status of the work.",
              },
              files_touched: {
                ...stringArrayJsonSchema,
                description: "Files inspected or modified.",
              },
              commands_run: {
                type: "array",
                description: "Shell commands run during the session.",
                items: {
                  type: "object",
                  additionalProperties: false,
                  required: ["cmd"],
                  properties: {
                    cmd: { type: "string", minLength: 1, maxLength: 2000 },
                    exit_code: { type: ["integer", "null"] },
                  },
                },
              },
              cwd: { type: "string" },
              diff_summary: { type: "string" },
              duration_ms: { type: "integer", minimum: 0 },
              harness: {
                type: "object",
                additionalProperties: false,
                description: "Self-reported per-session token usage.",
                required: ["model_id"],
                properties: {
                  model_id: { type: "string", minLength: 1, maxLength: 128 },
                  total_input_tokens: { type: "integer", minimum: 0 },
                  total_output_tokens: { type: "integer", minimum: 0 },
                  total_cache_read_tokens: { type: "integer", minimum: 0 },
                  total_cache_write_tokens: { type: "integer", minimum: 0 },
                },
              },
              transcript: {
                type: "array",
                description:
                  "Optional redacted transcript — only used when structured fields are empty. Prefer summary_points/details_sections to avoid summarizer cost.",
                items: {
                  type: "object",
                  additionalProperties: false,
                  required: ["role", "content"],
                  properties: {
                    role: { type: "string", minLength: 1 },
                    content: { type: "string" },
                  },
                },
              },
              checkpoint_index: { type: "integer", minimum: 1 },
            },
            required: ["session_id", "kind"],
          },
        },
        {
          name: "taskforce_session_log",
          description:
            "Return the Taskforce discovery preamble + consult history for a Claude Code session. Powers the `/taskforce` slash command — an agent or user can ask 'what did the hook pull into context this session?' without leaving Claude Code. Filters `document.consulted` events by `session_id` (which the UserPromptSubmit hook embeds on every discover call) and returns the per-match summary so the same preamble the hook injected can be replayed.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              session_id: {
                type: "string",
                minLength: 1,
                maxLength: 128,
                description: "Claude Code session id, sourced from the hook payload.",
              },
              limit: {
                type: "integer",
                minimum: 1,
                maximum: 200,
                description: "Max entries to return (default 50).",
              },
            },
            required: ["session_id"],
          },
        },
        {
          name: "taskforce_discover",
          description:
            "Look up the top 1–3 V2 documents related to a user prompt from the actor's library. Powers the hook-driven Taskforce workflow (TF-174 epic). The canonical caller is the UserPromptSubmit hook (TF-176), which POSTs the backend HTTP endpoint directly; this MCP tool exists as a fallback for harnesses without hook support and for agents that want to explicitly look up prior work mid-session. Each match returned is recorded as a `document.consulted` metrics event so the dashboard can attribute consultation back to a query.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              prompt: {
                type: "string",
                minLength: 1,
                maxLength: 8000,
                description: "The user prompt or research question to match against.",
              },
              cwd: { type: "string", description: "Working directory hint." },
              files: {
                ...stringArrayJsonSchema,
                description: "Files in scope for this turn.",
              },
              git_branch: { type: "string", description: "Active git branch." },
              recent_commands: {
                ...stringArrayJsonSchema,
                description: "Recent shell commands the harness saw.",
              },
              k: {
                type: "integer",
                minimum: 1,
                maximum: 3,
                description: "Max matches to return (hard cap 3). Defaults to 3.",
              },
              min_score: {
                type: "number",
                minimum: 0,
                maximum: 1,
                description: "Filter matches below this score. Defaults to 0.3.",
              },
              client: {
                type: "string",
                maxLength: 32,
                description:
                  "Self-reported harness (e.g. 'claude-code', 'codex', 'cursor'). Advisory provenance — drives cross-boundary reuse attribution (TF-202/C3). Identity stays the bearer token.",
              },
              demo: {
                type: "boolean",
                description: "Operate against demo documents.",
              },
            },
            required: ["prompt"],
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
      ];
    // Build the canonical taskforce_* entries + keep enderai_* as
    // deprecated aliases for one release. taskforce_discover and
    // taskforce_session_log are already canonical-named (TF-175/176) and
    // don't need duplication.
    const renamed: typeof primary = [];
    const aliases: typeof primary = [];
    for (const tool of primary) {
      const taskforceName = ENDERAI_TO_TASKFORCE_NAMES[tool.name];
      if (taskforceName) {
        renamed.push({ ...tool, name: taskforceName });
        aliases.push({
          ...tool,
          description: ALIAS_DEPRECATION_PREFIX + tool.description,
        });
      } else {
        renamed.push(tool);
      }
    }
    return { tools: [...renamed, ...aliases] };
  });

  function canonicalizeToolName(name: string): string {
    return TASKFORCE_TO_ENDERAI_ALIASES[name] ?? name;
  }

  server.setRequestHandler(CallToolRequestSchema, async (req) => {
    // Normalize taskforce_* canonical names → enderai_* (the existing
    // handler-dispatch keys). Two-way aliasing (TF-180): both names are
    // advertised in ListTools, both reach the same handler here.
    const name = canonicalizeToolName(req.params.name);

    try {
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

      if (name === "taskforce_discover") {
        const args = TaskforceDiscoverArgsSchema.parse(req.params.arguments ?? {});
        const bearerToken = opts.backendBearerTokenProvider?.();
        try {
          const result = await callTaskforceDiscover(
            { ...args, client: args.client ?? resolveDefaultClient(opts) },
            { bearerToken },
          );
          return toolJson(result);
        } catch (err) {
          return toolError(
            `taskforce_discover failed: ${err instanceof Error ? err.message : String(err)}`,
          );
        }
      }

      if (name === "taskforce_session_log") {
        const args = TaskforceSessionLogArgsSchema.parse(req.params.arguments ?? {});
        const bearerToken = opts.backendBearerTokenProvider?.();
        try {
          const result = await callTaskforceSessionLog(args, { bearerToken });
          return toolJson(result);
        } catch (err) {
          return toolError(
            `taskforce_session_log failed: ${err instanceof Error ? err.message : String(err)}`,
          );
        }
      }

      if (name === "taskforce_session_start") {
        const args = TaskforceSessionStartArgsSchema.parse(req.params.arguments ?? {});
        const bearerToken = opts.backendBearerTokenProvider?.();
        try {
          const result = await callTaskforceSessionStart(
            { ...args, client: args.client ?? resolveDefaultClient(opts) },
            { bearerToken },
          );
          return toolJson(result);
        } catch (err) {
          return toolError(
            `taskforce_session_start failed: ${err instanceof Error ? err.message : String(err)}`,
          );
        }
      }

      if (name === "taskforce_session_observe") {
        const args = TaskforceSessionObserveArgsSchema.parse(req.params.arguments ?? {});
        const bearerToken = opts.backendBearerTokenProvider?.();
        try {
          const result = await callTaskforceSessionObserve(
            { ...args, client: args.client ?? resolveDefaultClient(opts) },
            { bearerToken },
          );
          return toolJson(result);
        } catch (err) {
          return toolError(
            `taskforce_session_observe failed: ${err instanceof Error ? err.message : String(err)}`,
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
            `enderai_request is currently attached to execution ${auditExecutionId}. Run enderai_finish_document before switching to ${requestedAuditExecutionId}.`,
          );
        }

        if (
          isWriteLikeMethod(method) &&
          !auditExecutionId &&
          !unsafeWriteReason
        ) {
          return toolError(
            "enderai_request write-like calls require an active document. Run enderai_begin_document first so Taskforce can auto-hydrate relevant context; audit.execution_id does not replace an active document. You can also provide unsafe_write_reason for an explicit escape hatch.",
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
          active_document: activeDocumentState.documentId
            ? {
                id: activeDocumentState.documentId,
                title: activeDocumentState.title ?? null,
                started_at: activeDocumentState.startedAt ?? null,
                last_updated_at: activeDocumentState.lastUpdatedAt ?? null,
                demo: activeDocumentState.demo ?? false,
              }
            : null,
          session_ready: Boolean(bearerToken),
          next: {
            begin_tool: "enderai_begin_document",
            update_tool: "enderai_update_document",
            finish_tool: "enderai_finish_document",
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
