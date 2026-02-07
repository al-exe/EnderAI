import { describe, expect, it, vi } from "vitest";

import { enderaiFetch } from "../src/http.js";

// Avoid touching the network: mock global fetch.
const mockFetch = vi.fn();
// @ts-expect-error - vitest in Node.
globalThis.fetch = mockFetch;

describe("enderaiFetch", () => {
  it("rejects non-absolute path", async () => {
    await expect(
      enderaiFetch({ method: "GET", path: "https://example.com" }),
    ).rejects.toThrow(/must start with/);
  });

  it("includes bearer token header when configured", async () => {
    process.env.ENDERAI_BASE_URL = "https://enderai-backend.onrender.com";
    process.env.ENDERAI_BEARER_TOKEN = "testtoken";

    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await enderaiFetch({ method: "GET", path: "/api/v1/utils/health-check/" });

    const call = mockFetch.mock.calls[0];
    expect(call[0].toString()).toContain("/api/v1/utils/health-check/");
    expect(call[1].headers.authorization).toBe("Bearer testtoken");
  });
});
