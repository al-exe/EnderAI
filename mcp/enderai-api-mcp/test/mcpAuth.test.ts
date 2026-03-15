import { beforeEach, describe, expect, it, vi } from "vitest";

import { validateIncomingMcpBearerToken } from "../src/mcpAuth.js";

const mockFetch = vi.fn();
// @ts-expect-error - vitest in Node.
globalThis.fetch = mockFetch;

describe("validateIncomingMcpBearerToken", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("accepts the shared MCP bearer token without a backend lookup", async () => {
    const result = await validateIncomingMcpBearerToken({
      providedBearerToken: "shared-token",
      sharedBearerToken: "shared-token",
    });

    expect(result).toEqual({ ok: true, via: "shared" });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("rejects requests with no MCP bearer token", async () => {
    const result = await validateIncomingMcpBearerToken({
      providedBearerToken: undefined,
      sharedBearerToken: "shared-token",
    });

    expect(result).toEqual({
      ok: false,
      statusCode: 401,
      message: "Unauthorized",
    });
  });

  it("validates per-user MCP tokens against the backend", async () => {
    process.env.ENDERAI_BASE_URL = "https://enderai-backend.onrender.com";

    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ valid: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const result = await validateIncomingMcpBearerToken({
      providedBearerToken: "user-mcp-token",
      sharedBearerToken: "shared-token",
    });

    expect(result).toEqual({ ok: true, via: "per_user" });

    const call = mockFetch.mock.calls[0];
    expect(call[0].toString()).toContain(
      "/api/v1/agent-credentials/validate-mcp-token",
    );
    expect(call[1].headers.authorization).toBe("Bearer user-mcp-token");
  });

  it("maps invalid per-user MCP tokens to unauthorized", async () => {
    process.env.ENDERAI_BASE_URL = "https://enderai-backend.onrender.com";

    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Could not validate credentials" }), {
        status: 403,
        headers: { "content-type": "application/json" },
      }),
    );

    const result = await validateIncomingMcpBearerToken({
      providedBearerToken: "bad-user-token",
      sharedBearerToken: undefined,
    });

    expect(result).toEqual({
      ok: false,
      statusCode: 401,
      message: "Unauthorized",
    });
  });

  it("maps backend validation failures to service unavailable", async () => {
    process.env.ENDERAI_BASE_URL = "https://enderai-backend.onrender.com";

    mockFetch.mockRejectedValueOnce(new Error("network down"));

    const result = await validateIncomingMcpBearerToken({
      providedBearerToken: "user-mcp-token",
      sharedBearerToken: undefined,
    });

    expect(result).toEqual({
      ok: false,
      statusCode: 503,
      message: "MCP token validation unavailable",
    });
  });
});
