import { enderaiFetch } from "./http.js";

export type McpAuthorizationResult =
  | {
      ok: true;
      via: "shared";
    }
  | {
      ok: true;
      via: "per_user";
      backendBearerToken: string;
    }
  | { ok: false; statusCode: number; message: string };

export async function validateIncomingMcpBearerToken(args: {
  providedBearerToken?: string;
  sharedBearerToken?: string;
}): Promise<McpAuthorizationResult> {
  const { providedBearerToken, sharedBearerToken } = args;

  if (sharedBearerToken && providedBearerToken === sharedBearerToken) {
    return { ok: true, via: "shared" };
  }
  if (!providedBearerToken) {
    return { ok: false, statusCode: 401, message: "Unauthorized" };
  }

  try {
    const res = await enderaiFetch({
      method: "POST",
      path: "/api/v1/agent-credentials/validate-mcp-token",
      bearerToken: providedBearerToken,
    });
    if (res.ok) {
      return {
        ok: true,
        via: "per_user",
        backendBearerToken: providedBearerToken,
      };
    }
    if (res.status >= 500) {
      return {
        ok: false,
        statusCode: 503,
        message: "MCP token validation unavailable",
      };
    }
    return { ok: false, statusCode: 401, message: "Unauthorized" };
  } catch {
    return {
      ok: false,
      statusCode: 503,
      message: "MCP token validation unavailable",
    };
  }
}
