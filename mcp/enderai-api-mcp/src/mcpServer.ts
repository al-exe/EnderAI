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

export function createMcpServer(opts: McpServerOptions = {}): Server {
  const server = new Server(
    { name: "enderai-api", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );

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
        const sessionToken = opts.backendBearerTokenProvider?.();
        const res = await enderaiFetch({
          ...args,
          bearerToken: args.bearerToken ?? sessionToken,
        });
        return { content: [{ type: "text", text: JSON.stringify(res, null, 2) }] };
      }

      if (name === "enderai_openapi") {
        const sessionToken = opts.backendBearerTokenProvider?.();
        const res = await enderaiFetch({
          method: "GET",
          path: "/api/v1/openapi.json",
          bearerToken: sessionToken,
        });
        return { content: [{ type: "text", text: JSON.stringify(res, null, 2) }] };
      }

      if (name === "enderai_health_check") {
        const sessionToken = opts.backendBearerTokenProvider?.();
        const res = await enderaiFetch({
          method: "GET",
          path: "/api/v1/utils/health-check/",
          bearerToken: sessionToken,
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
