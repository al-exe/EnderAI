import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { callTaskforceDiscover } from "../src/taskforce/discover.js";

const realFetch = globalThis.fetch.bind(globalThis);
const mockFetch = vi.fn();

beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as { fetch: unknown }).fetch = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : (input as Request).url;
      if (url.startsWith("http://127.0.0.1")) {
        return await realFetch(input as Parameters<typeof realFetch>[0], init);
      }
      return await mockFetch(input, init);
    },
  );
  process.env.ENDERAI_BASE_URL = "https://enderai-backend.test";
  delete process.env.ENDERAI_BEARER_TOKEN;
});

afterEach(() => {
  (globalThis as { fetch: typeof realFetch }).fetch = realFetch;
});

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("callTaskforceDiscover", () => {
  it("POSTs the discover endpoint with the JSON body and demo query", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ query_id: "00000000-0000-0000-0000-000000000001", matches: [] }),
    );

    const result = await callTaskforceDiscover(
      { prompt: "library polish", files: ["a.tsx"], demo: true },
      { bearerToken: "tok" },
    );

    expect(result.query_id).toBe("00000000-0000-0000-0000-000000000001");
    expect(result.matches).toEqual([]);

    const call = mockFetch.mock.calls[0];
    const url = String(call[0]);
    const init = call[1] as RequestInit;
    expect(url).toContain("/api/v1/v2/taskforce/discover");
    expect(url).toContain("demo=true");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ authorization: "Bearer tok" });
    expect(JSON.parse(String(init.body))).toEqual({
      prompt: "library polish",
      files: ["a.tsx"],
    });
  });

  it("returns matches with the documented shape", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        query_id: "00000000-0000-0000-0000-000000000002",
        matches: [
          {
            document_id: "11111111-1111-1111-1111-111111111111",
            title: "Library polish",
            score: 0.81,
            confidence_band: "high",
            match_reasons: ["Title tokens overlap on 'library', 'polish'"],
            summary_markdown: "Cleanup of the metrics page.",
            last_touched_at: "2026-05-20T17:00:00Z",
            outcome: null,
            rediscovery_cost_tokens: 17000,
            consult_token_cost: 120,
          },
        ],
      }),
    );

    const result = await callTaskforceDiscover({ prompt: "library polish" });
    expect(result.matches).toHaveLength(1);
    expect(result.matches[0].confidence_band).toBe("high");
    expect(result.matches[0].rediscovery_cost_tokens).toBe(17000);
  });

  it("throws on a non-OK response with the backend detail", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Authentication required" }, 401),
    );
    await expect(callTaskforceDiscover({ prompt: "anything" })).rejects.toThrow(
      /401.*Authentication required/,
    );
  });
});
