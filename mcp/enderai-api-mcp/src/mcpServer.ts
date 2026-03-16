import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import { enderaiFetch, type ResponseSummary } from "./http.js";

export type McpServerOptions = {
  backendBearerTokenProvider?: () => string | undefined;
};

const AUDIT_MAX_BYTES = 48_000;
const AUDIT_PREVIEW_CHARS = 8_000;
const DEFAULT_CONTEXT_PACK_CASE_LIMIT = 3;

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
    topic_id: z.string().uuid().optional(),
    topic_title: z.string().min(1).optional(),
    workflow_key: z.string().min(1).optional(),
    topic_description: z.string().optional(),
    aliases: z.array(z.string()).optional(),
    request_summary: z.string().min(1),
    case_title: z.string().min(1).optional(),
    files: z.array(z.string()).optional(),
    symbols: z.array(z.string()).optional(),
    errors: z.array(z.string()).optional(),
    symptoms: z.array(z.string()).optional(),
    auto_hydrate: z.boolean().optional(),
    max_cases_per_topic: z.number().int().positive().optional(),
  })
  .strict()
  .refine(
    (value) =>
      Boolean(
        trimToUndefined(value.topic_id) ||
          trimToUndefined(value.topic_title) ||
          trimToUndefined(value.workflow_key),
      ),
    {
      message: "Provide topic_id, topic_title, or workflow_key so the case can be attached to a topic.",
    },
  );

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

const EnderaiRequestArgsSchema = z
  .object({
    method: z.string().min(1),
    path: z.string().min(1),
    query: z.record(z.unknown()).optional(),
    headers: z.record(z.string()).optional(),
    json: z.unknown().optional(),
    text: z.string().optional(),
    bearerToken: z.string().optional(),
    timeoutMs: z.number().int().positive().optional(),
    audit: z
      .object({
        intent: z.string().min(1).optional(),
        case_id: z.string().uuid().optional(),
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
  const slug = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
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

function asRecord(value: unknown): Record<string, any> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, any>;
}

function pruneUndefined<T extends Record<string, unknown>>(value: T): T {
  return Object.fromEntries(
    Object.entries(value).filter(([, entry]) => entry !== undefined),
  ) as T;
}

function extractCaseContext(resData: unknown): { caseId?: string; topicId?: string } {
  const data = asRecord(resData);
  if (typeof data.id === "string") {
    return {
      caseId: typeof data.topic_id === "string" ? data.id : undefined,
      topicId: typeof data.topic_id === "string" ? data.topic_id : undefined,
    };
  }

  const caseData = asRecord(data.case);
  if (typeof caseData.id === "string") {
    return {
      caseId: caseData.id,
      topicId: typeof caseData.topic_id === "string" ? caseData.topic_id : undefined,
    };
  }

  const topicData = asRecord(data.topic);
  if (typeof topicData.id === "string") {
    return { topicId: topicData.id };
  }

  return {};
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
    caseId?: string;
    topicId?: string;
    depth: number;
  } = { depth: 0 };

  function setActiveCaseContext(caseId?: string, topicId?: string): void {
    if (caseId) auditState.caseId = caseId;
    if (topicId) auditState.topicId = topicId;
  }

  function clearActiveCaseContext(): void {
    delete auditState.caseId;
    delete auditState.topicId;
  }

  function resolveCaseId(explicitCaseId: string | undefined, toolName: string): string {
    if (explicitCaseId) {
      if (auditState.caseId && auditState.caseId !== explicitCaseId) {
        throw new Error(
          `${toolName} is currently attached to case ${auditState.caseId}. Run enderai_finish_case before switching to case ${explicitCaseId}.`,
        );
      }
      auditState.caseId = explicitCaseId;
      return explicitCaseId;
    }
    if (auditState.caseId) return auditState.caseId;
    throw new Error(
      `${toolName} requires an active case. Run enderai_begin_case first or provide case_id.`,
    );
  }

  async function appendCaseEvent(params: {
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

  async function tryCreateCaseEvent(params: {
    bearerToken?: string;
    caseId?: string;
    type: string;
    message: string;
    data: unknown;
  }): Promise<void> {
    if (!params.caseId) return;
    if (!params.bearerToken) return;
    if (auditState.depth > 0) return;

    auditState.depth += 1;
    try {
      await appendCaseEvent({
        bearerToken: params.bearerToken,
        caseId: params.caseId,
        type: params.type,
        message: params.message,
        data: asRecord(params.data),
      });
    } catch {
      // Best-effort audit trail. Never fail the primary tool request.
    } finally {
      auditState.depth -= 1;
    }
  }

  async function auditWorkflowTool(params: {
    bearerToken?: string;
    caseId?: string;
    message: string;
    tool: string;
    request: unknown;
    response: unknown;
  }): Promise<void> {
    await tryCreateCaseEvent({
      bearerToken: params.bearerToken,
      caseId: params.caseId,
      type: "mcp",
      message: params.message,
      data: capJson(
        redactSecrets({
          tool: params.tool,
          request: params.request,
          response: params.response,
          case_context: {
            case_id: params.caseId ?? auditState.caseId ?? null,
            topic_id: auditState.topicId ?? null,
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

    await tryCreateCaseEvent({
      bearerToken: sessionToken,
      caseId: auditState.caseId,
      type: "mcp",
      message: params.message,
      data: capJson(
        redactSecrets({
          tool: params.name,
          request: { method: "GET", path: params.path },
          response: res,
          case_context: {
            case_id: auditState.caseId ?? null,
            topic_id: auditState.topicId ?? null,
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
            "Begin a guided Topic/Case workflow. Creates or attaches to a Topic, optionally builds a ContextPack, creates a new Case, remembers the returned ids for this MCP session, and returns the ids needed for enderai_update_case and enderai_finish_case.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              topic_id: {
                type: "string",
                description: "Existing Topic id to attach the new case to.",
              },
              topic_title: {
                type: "string",
                description: "Human-facing Topic title to create when topic_id is not provided.",
              },
              workflow_key: {
                type: "string",
                description:
                  "Optional stable topic key when creating a new Topic. If omitted, it is derived from topic_title.",
              },
              topic_description: {
                type: "string",
                description: "Optional Topic description to persist when creating a new Topic.",
              },
              aliases: {
                ...stringArrayJsonSchema,
                description: "Optional extra aliases to help ContextPack selection.",
              },
              request_summary: {
                type: "string",
                description: "Short statement of the new work request or problem to investigate.",
              },
              case_title: {
                type: "string",
                description: "Optional Case title if it should differ from the request summary.",
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
              auto_hydrate: {
                type: "boolean",
                description:
                  "Whether to build and attach a ContextPack immediately after the case starts. Defaults to true.",
              },
              max_cases_per_topic: {
                type: "integer",
                description:
                  "Optional limit for how many prior cases the ContextPack builder should include.",
                minimum: 1,
              },
            },
            required: ["request_summary"],
          },
        },
        {
          name: "enderai_update_case",
          description:
            "Patch the active Case document with new evidence, hypotheses, commands, or changes. Requires a prior enderai_begin_case call in this MCP session unless case_id is supplied. Use enderai_finish_case, not this tool, to close a case.",
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
                  "Optional progress note to append as a Case event after the case patch succeeds.",
              },
              progress_data: {
                ...looseObjectJsonSchema,
                description: "Optional structured payload for the progress event.",
              },
            },
          },
        },
        {
          name: "enderai_finish_case",
          description:
            "Apply final case updates and close the active Case with a terminal status. Requires a prior enderai_begin_case call in this MCP session unless case_id is supplied. Clears the active case context on success.",
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
                  "Optional closing note to append as a Case event after the case closes.",
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
            "Make an HTTP request to the EnderAI backend configured by ENDERAI_BASE_URL. Adds Authorization: Bearer from ENDERAI_BEARER_TOKEN if set.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              method: { type: "string", description: "HTTP method (GET/POST/...)." },
              path: {
                type: "string",
                description:
                  'Request path starting with "/". Example: "/api/v1/topics/".',
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
              timeoutMs: {
                type: "integer",
                description: "Optional per-call timeout override (ms).",
                minimum: 1,
              },
              audit: {
                type: "object",
                description:
                  "Optional per-call audit metadata. When a Case id is known, this server can append a Case event with request/response metadata (secrets redacted).",
                additionalProperties: false,
                properties: {
                  intent: {
                    type: "string",
                    description: "Human-readable reason for the call.",
                  },
                  case_id: {
                    type: "string",
                    description:
                      "Override the current Case id (also updates session context).",
                  },
                },
              },
            },
            required: ["method", "path"],
          },
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
        if (auditState.caseId) {
          return toolError(
            `A case is already active in this MCP session (${auditState.caseId}). Run enderai_finish_case before beginning a new one.`,
          );
        }

        const bearerToken = opts.backendBearerTokenProvider?.();
        const workflowKey = trimToUndefined(args.workflow_key);
        const topicTitle =
          trimToUndefined(args.topic_title) ??
          (workflowKey ? humanizeWorkflowKey(workflowKey) : undefined);
        const requestSummary = trimToUndefined(args.request_summary)!;
        const caseTitle = trimToUndefined(args.case_title) ?? requestSummary;

        let topicRes: ResponseSummary;
        if (args.topic_id) {
          topicRes = await enderaiFetch({
            method: "GET",
            path: `/api/v1/topics/${args.topic_id}`,
            bearerToken,
          });
          if (!topicRes.ok) {
            throw new Error(
              `enderai_begin_case failed to load the Topic: ${extractErrorDetail(topicRes)} (status ${topicRes.status}).`,
            );
          }
        } else {
          if (!topicTitle) {
            throw new Error(
              "enderai_begin_case requires topic_id, topic_title, or workflow_key so the case can be attached to a topic.",
            );
          }
          topicRes = await enderaiFetch({
            method: "POST",
            path: "/api/v1/topics/",
            bearerToken,
            json: pruneUndefined({
              title: topicTitle,
              workflow_key: workflowKey,
              description: trimToUndefined(args.topic_description),
              aliases: args.aliases,
            }),
          });
          if (!topicRes.ok) {
            throw new Error(
              `enderai_begin_case failed to create the Topic: ${extractErrorDetail(topicRes)} (status ${topicRes.status}).`,
            );
          }
        }

        const topicData = asRecord(topicRes.data);
        const topicId = typeof topicData.id === "string" ? topicData.id : undefined;
        if (!topicId) {
          throw new Error("enderai_begin_case did not receive a topic id from /api/v1/topics.");
        }

        let contextPack: unknown | null = null;
        if (args.auto_hydrate !== false) {
          const contextPackRes = await enderaiFetch({
            method: "POST",
            path: "/api/v1/context-packs/build",
            bearerToken,
            json: pruneUndefined({
              topic_id: topicId,
              title: caseTitle,
              request_summary: requestSummary,
              aliases: args.aliases,
              files: args.files,
              symbols: args.symbols,
              errors: args.errors,
              symptoms: args.symptoms,
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

        const contextPackSnapshot = asRecord(contextPack).context_pack_snapshot;
        const caseRes = await enderaiFetch({
          method: "POST",
          path: "/api/v1/cases/",
          bearerToken,
          json: pruneUndefined({
            topic_id: topicId,
            title: caseTitle,
            source: "mcp",
            input_summary: requestSummary,
            summary_current: requestSummary,
            files: args.files,
            symbols: args.symbols,
            errors: args.errors,
            symptoms: args.symptoms,
            context_pack_snapshot:
              Object.keys(asRecord(contextPackSnapshot)).length > 0
                ? contextPackSnapshot
                : undefined,
          }),
        });
        if (!caseRes.ok) {
          throw new Error(
            `enderai_begin_case failed to create the case: ${extractErrorDetail(caseRes)} (status ${caseRes.status}).`,
          );
        }

        const caseContext = extractCaseContext(caseRes.data);
        if (!caseContext.caseId || !caseContext.topicId) {
          throw new Error(
            "enderai_begin_case did not receive case and topic ids from /api/v1/cases/.",
          );
        }
        setActiveCaseContext(caseContext.caseId, caseContext.topicId);

        const result = {
          topic: topicRes.data,
          case: caseRes.data,
          context_pack: contextPack,
          next: {
            update_tool: "enderai_update_case",
            finish_tool: "enderai_finish_case",
            case_id: caseContext.caseId,
            topic_id: caseContext.topicId,
          },
        };
        await auditWorkflowTool({
          bearerToken,
          caseId: caseContext.caseId,
          message: "Begin case",
          tool: "enderai_begin_case",
          request: args,
          response: result,
        });
        return toolJson(result);
      }

      if (name === "enderai_update_case") {
        const args = UpdateCaseArgsSchema.parse(req.params.arguments ?? {});
        const caseId = resolveCaseId(args.case_id, "enderai_update_case");
        const bearerToken = opts.backendBearerTokenProvider?.();

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
          typeof caseData.topic_id === "string" ? caseData.topic_id : auditState.topicId,
        );

        let progressEvent: unknown | null = null;
        if (args.progress_note) {
          const progressRes = await appendCaseEvent({
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
            topic_id: caseData.topic_id ?? auditState.topicId ?? null,
          },
        };
        await auditWorkflowTool({
          bearerToken,
          caseId,
          message: "Update case",
          tool: "enderai_update_case",
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

        const caseId = resolveCaseId(args.case_id, "enderai_finish_case");
        const bearerToken = opts.backendBearerTokenProvider?.();
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
          typeof caseData.topic_id === "string" ? caseData.topic_id : auditState.topicId,
        );

        let closingEvent: unknown | null = null;
        if (args.closing_note) {
          const closingRes = await appendCaseEvent({
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
            topic_id: caseData.topic_id ?? auditState.topicId ?? null,
          },
        };
        await auditWorkflowTool({
          bearerToken,
          caseId,
          message: "Finish case",
          tool: "enderai_finish_case",
          request: args,
          response: result,
        });
        clearActiveCaseContext();
        return toolJson(result);
      }

      if (name === "enderai_request") {
        const args = EnderaiRequestArgsSchema.parse(req.params.arguments ?? {});
        const { audit, ...reqArgs } = args;
        const sessionToken = opts.backendBearerTokenProvider?.();
        const bearerToken = reqArgs.bearerToken ?? sessionToken;
        const auditCaseId = audit?.case_id ?? auditState.caseId;
        const auditIntent = audit?.intent;

        if (audit?.case_id) auditState.caseId = audit.case_id;

        const res = await enderaiFetch({
          ...reqArgs,
          bearerToken,
        });

        if (res.ok) {
          const normalizedPath = args.path.replace(/\/+$/, "");
          const method = args.method.toUpperCase();
          const caseContext = extractCaseContext(res.data);
          if (
            caseContext.caseId &&
            caseContext.topicId &&
            (normalizedPath === "/api/v1/cases" ||
              normalizedPath === "/api/v1/cases/" ||
              normalizedPath.startsWith("/api/v1/cases/"))
          ) {
            setActiveCaseContext(caseContext.caseId, caseContext.topicId);
          } else if (
            caseContext.topicId &&
            (method === "GET" || method === "POST" || method === "PATCH") &&
            (normalizedPath === "/api/v1/topics" ||
              normalizedPath === "/api/v1/topics/" ||
              normalizedPath.startsWith("/api/v1/topics/"))
          ) {
            setActiveCaseContext(undefined, caseContext.topicId);
          }
        }

        const auditData = capJson(
          redactSecrets({
            tool: "enderai_request",
            intent: auditIntent ?? null,
            request: {
              method: args.method,
              path: args.path,
              query: args.query,
              headers: args.headers,
              json: args.json,
              text: args.text,
              timeoutMs: args.timeoutMs,
            },
            response: res,
            case_context: {
              case_id: auditCaseId ?? auditState.caseId ?? null,
              topic_id: auditState.topicId ?? null,
            },
          }),
        );
        const message = auditIntent?.trim() || `${args.method.toUpperCase()} ${args.path}`;
        await tryCreateCaseEvent({
          bearerToken,
          caseId: auditCaseId ?? auditState.caseId,
          type: "mcp",
          message,
          data: auditData,
        });

        return toolJson(res);
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
