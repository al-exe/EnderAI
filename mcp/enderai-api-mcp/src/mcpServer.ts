import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import { enderaiFetch } from "./http.js";

export type McpServerOptions = {
  // Optional backend bearer token provider used for all tool calls in this server instance.
  // This enables a hosted MCP server to act "per user" by binding a backend token to a session,
  // while still supporting token rotation during that session.
  backendBearerTokenProvider?: () => string | undefined;
};

const AUDIT_MAX_BYTES = 48_000;
const AUDIT_PREVIEW_CHARS = 8_000;

const REDACT_KEYS = new Set([
  // Common auth / secret fields.
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

function shouldRedactKey(key: string): boolean {
  const k = key.trim().toLowerCase();
  if (!k) return false;
  return REDACT_KEYS.has(k);
}

function redactSecrets(value: unknown, keyHint?: string): unknown {
  if (keyHint && shouldRedactKey(keyHint)) return "[REDACTED]";
  if (value === null) return null;
  if (value === undefined) return undefined;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (Array.isArray(value)) return value.map((v) => redactSecrets(v));
  if (typeof value !== "object") return String(value);

  const obj = value as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    out[k] = redactSecrets(v, k);
  }
  return out;
}

function capJson(value: unknown): unknown {
  // Keep audit events lightweight; large payloads (OpenAPI, dumps) can freeze UIs.
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

export function createMcpServer(opts: McpServerOptions = {}): Server {
  const server = new Server(
    { name: "enderai-api", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );

  // Per-session state: createSession() constructs a new server instance per MCP session.
  const auditState: {
    runId?: string;
    taskId?: string;
    depth: number;
  } = { depth: 0 };

  async function tryCreateRunEvent(params: {
    bearerToken?: string;
    runId?: string;
    type: string;
    message: string;
    data: unknown;
  }): Promise<void> {
    if (!params.runId) return;
    if (!params.bearerToken) return;
    if (auditState.depth > 0) return;

    auditState.depth += 1;
    try {
      await enderaiFetch({
        method: "POST",
        path: `/api/v1/runs/${params.runId}/events`,
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
    runId?: string;
    libraryItemId?: string;
    createdAt?: string | null;
  }): Promise<unknown | null> {
    if (!params.runId || !params.libraryItemId || !params.bearerToken) return null;
    if (auditState.depth > 0) return null;

    auditState.depth += 1;
    try {
      const res = await enderaiFetch({
        method: "POST",
        path: `/api/v1/runs/${params.runId}/memory-links`,
        bearerToken: params.bearerToken,
        json: {
          library_item_id: params.libraryItemId,
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

  function extractRunStartIds(resData: unknown): { runId?: string; taskId?: string } {
    const d = resData as any;
    const runId = typeof d?.run?.id === "string" ? d.run.id : undefined;
    const taskId = typeof d?.task?.id === "string" ? d.task.id : undefined;
    return { runId, taskId };
  }

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
          // Short human-readable reason for the call; becomes the Run event message.
          intent: z.string().min(1).optional(),
          // Override the current Run id (also updates the session's run context).
          run_id: z.string().uuid().optional(),
        })
        .optional(),
    })
    .refine((v) => !(v.json !== undefined && v.text !== undefined), {
      message: 'Provide only one of "json" or "text".',
    });

  server.setRequestHandler(ListToolsRequestSchema, async () => {
    return {
      tools: [
        {
          name: "enderai_request",
          description:
            "Make an HTTP request to the EnderAI backend configured by ENDERAI_BASE_URL. Adds Authorization: Bearer from ENDERAI_BEARER_TOKEN if set.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            properties: {
              method: { type: "string", description: "HTTP method (GET/POST/...)" },
              path: {
                type: "string",
                description:
                  'Request path starting with "/". Example: "/api/v1/tasks/".',
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
                  "Optional per-call audit metadata. When a Run id is known, this server can append an audit event with request/response (secrets redacted).",
                additionalProperties: false,
                properties: {
                  intent: {
                    type: "string",
                    description: "Human-readable reason for the call.",
                  },
                  run_id: {
                    type: "string",
                    description:
                      "Override the current Run id (also updates session context).",
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
      if (name === "enderai_request") {
        const args = EnderaiRequestArgsSchema.parse(req.params.arguments ?? {});
        const { audit, ...reqArgs } = args;
        const sessionToken = opts.backendBearerTokenProvider?.();
        const bearerToken = reqArgs.bearerToken ?? sessionToken;
        const auditRunId = audit?.run_id ?? auditState.runId;
        const auditIntent = audit?.intent;

        // Allow the caller to explicitly set the run context (useful for clients that
        // start a run outside of MCP, then want MCP calls to attach to it).
        if (audit?.run_id) auditState.runId = audit.run_id;

        const res = await enderaiFetch({
          ...reqArgs,
          bearerToken,
        });

        // If this call started a run, update session context so subsequent calls auto-attach.
        const isRunStart =
          args.method.toUpperCase() === "POST" &&
          args.path.replace(/\/+$/, "") === "/api/v1/runs/start";
        if (isRunStart && res.ok) {
          const ids = extractRunStartIds(res.data);
          if (ids.runId) auditState.runId = ids.runId;
          if (ids.taskId) auditState.taskId = ids.taskId;
        }

        const auto: Record<string, unknown> = {};
        const normalizedPath = args.path.replace(/\/+$/, "");
        const isLibraryCreate =
          args.method.toUpperCase() === "POST" && normalizedPath === "/api/v1/library";
        if (isLibraryCreate && res.ok) {
          const d = res.data as any;
          const liId = typeof d?.id === "string" ? d.id : undefined;
          const createdAt = typeof d?.created_at === "string" ? d.created_at : null;
          const linkRes = await tryAutoLinkLibraryItem({
            bearerToken,
            runId: auditRunId ?? auditState.runId,
            libraryItemId: liId,
            createdAt,
          });
          if (linkRes) auto.memory_link = capJson(redactSecrets(linkRes));
        }

        // Best-effort: append MCP call as a Run event when we have a run id.
        // NOTE: redacts secrets and caps payload size to keep the DB/UI healthy.
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
            auto,
            run_context: {
              run_id: auditRunId ?? auditState.runId ?? null,
              task_id: auditState.taskId ?? null,
            },
          }),
        );
        const msg = auditIntent?.trim() || `${args.method.toUpperCase()} ${args.path}`;
        await tryCreateRunEvent({
          bearerToken,
          runId: auditRunId ?? auditState.runId,
          type: "mcp",
          message: msg,
          data: auditData,
        });

        return { content: [{ type: "text", text: JSON.stringify(res, null, 2) }] };
      }

      if (name === "enderai_openapi") {
        const sessionToken = opts.backendBearerTokenProvider?.();
        const bearerToken = sessionToken;
        const res = await enderaiFetch({
          method: "GET",
          path: "/api/v1/openapi.json",
          bearerToken,
        });

        await tryCreateRunEvent({
          bearerToken,
          runId: auditState.runId,
          type: "mcp",
          message: "Fetch OpenAPI schema",
          data: capJson(
            redactSecrets({
              tool: "enderai_openapi",
              request: { method: "GET", path: "/api/v1/openapi.json" },
              response: res,
              run_context: { run_id: auditState.runId ?? null, task_id: auditState.taskId ?? null },
            }),
          ),
        });

        return { content: [{ type: "text", text: JSON.stringify(res, null, 2) }] };
      }

      if (name === "enderai_health_check") {
        const sessionToken = opts.backendBearerTokenProvider?.();
        const bearerToken = sessionToken;
        const res = await enderaiFetch({
          method: "GET",
          path: "/api/v1/utils/health-check/",
          bearerToken,
        });

        await tryCreateRunEvent({
          bearerToken,
          runId: auditState.runId,
          type: "mcp",
          message: "Health check",
          data: capJson(
            redactSecrets({
              tool: "enderai_health_check",
              request: { method: "GET", path: "/api/v1/utils/health-check/" },
              response: res,
              run_context: { run_id: auditState.runId ?? null, task_id: auditState.taskId ?? null },
            }),
          ),
        });

        return { content: [{ type: "text", text: JSON.stringify(res, null, 2) }] };
      }

      return {
        content: [{ type: "text", text: `Unknown tool: ${name}` }],
        isError: true,
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { content: [{ type: "text", text: msg }], isError: true };
    }
  });

  return server;
}
