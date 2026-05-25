import type { McpAuthorizationResult } from "./mcpAuth.js";

export function resolveSessionBackendBearerToken(args: {
  mcpAuth: McpAuthorizationResult;
}): string | undefined {
  if (args.mcpAuth.ok && args.mcpAuth.via === "per_user") {
    return args.mcpAuth.backendBearerToken;
  }

  return undefined;
}
