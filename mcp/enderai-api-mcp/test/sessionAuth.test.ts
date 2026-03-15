import { describe, expect, it } from "vitest";

import { resolveSessionBackendBearerToken } from "../src/sessionAuth.js";

describe("resolveSessionBackendBearerToken", () => {
  it("reuses the validated per-user MCP bearer token by default", () => {
    const token = resolveSessionBackendBearerToken({
      req: { headers: {} },
      mcpAuth: {
        ok: true,
        via: "per_user",
        backendBearerToken: "user-mcp-token",
      },
    });

    expect(token).toBe("user-mcp-token");
  });

  it("prefers the legacy backend header over the validated MCP bearer token", () => {
    const token = resolveSessionBackendBearerToken({
      req: {
        headers: {
          "x-enderai-backend-token": "Bearer legacy-backend-token",
        },
      },
      mcpAuth: {
        ok: true,
        via: "per_user",
        backendBearerToken: "user-mcp-token",
      },
    });

    expect(token).toBe("legacy-backend-token");
  });

  it("returns undefined when neither a per-user session token nor a legacy header is available", () => {
    const token = resolveSessionBackendBearerToken({
      req: { headers: {} },
      mcpAuth: { ok: true, via: "shared" },
    });

    expect(token).toBeUndefined();
  });
});
