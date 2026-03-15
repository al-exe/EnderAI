import http from "node:http";

import type { McpAuthorizationResult } from "./mcpAuth.js";

type HeaderCarrier = Pick<http.IncomingMessage, "headers">;

export function readBackendBearerToken(req: HeaderCarrier): string | undefined {
  // Allow passing the EnderAI backend token separately from the MCP server auth header.
  // This remains as a legacy compatibility path for older hosted MCP clients.
  const raw = getHeaderString(req, "x-enderai-backend-token")?.trim();
  if (raw) {
    // Be tolerant: some clients include the "Bearer " prefix even on the token header.
    const m = /^Bearer\s+(.+)$/.exec(raw);
    return m?.[1]?.trim() || raw;
  }

  const auth = getHeaderString(req, "x-enderai-backend-authorization")?.trim();
  if (!auth) return undefined;
  const m = /^Bearer\s+(.+)$/.exec(auth);
  return m?.[1]?.trim() || undefined;
}

export function resolveSessionBackendBearerToken(args: {
  req: HeaderCarrier;
  mcpAuth: McpAuthorizationResult;
}): string | undefined {
  const legacyBackendToken = readBackendBearerToken(args.req);
  if (legacyBackendToken) return legacyBackendToken;

  if (args.mcpAuth.ok && args.mcpAuth.via === "per_user") {
    return args.mcpAuth.backendBearerToken;
  }

  return undefined;
}

function getHeaderString(req: HeaderCarrier, name: string): string | undefined {
  const v = req.headers[name.toLowerCase()];
  if (!v) return undefined;
  return Array.isArray(v) ? v[0] : v;
}
