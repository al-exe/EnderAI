import { describe, expect, it } from "vitest";

import { resolveSessionBackendBearerToken } from "../src/sessionAuth.js";

describe("resolveSessionBackendBearerToken", () => {
  it("reuses the validated per-user MCP bearer token by default", () => {
    const token = resolveSessionBackendBearerToken({
      mcpAuth: {
        ok: true,
        via: "per_user",
        backendBearerToken: "user-mcp-token",
      },
    });

    expect(token).toBe("user-mcp-token");
  });

  it("returns undefined when the session was established with a shared server token", () => {
    const token = resolveSessionBackendBearerToken({
      mcpAuth: { ok: true, via: "shared" },
    });

    expect(token).toBeUndefined();
  });
});
