import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { callTaskforceSessionLog } from "../src/taskforce/sessionLog.js";

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

describe("callTaskforceSessionLog", () => {
  it("GETs with session_id + optional limit", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ session_id: "s1", entries: [] }),
    );
    const result = await callTaskforceSessionLog(
      { session_id: "s1", limit: 25 },
      { bearerToken: "tok" },
    );
    expect(result.session_id).toBe("s1");
    expect(result.entries).toEqual([]);

    const url = String(mockFetch.mock.calls[0][0]);
    expect(url).toContain("/api/v1/v2/taskforce/session-log");
    expect(url).toContain("session_id=s1");
    expect(url).toContain("limit=25");
  });

  it("returns entries with the documented shape", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        session_id: "s2",
        entries: [
          {
            document_id: "11111111-1111-1111-1111-111111111111",
            title: "TF-156 polish",
            score: 0.81,
            confidence_band: "high",
            match_reasons: ["Title tokens overlap"],
            summary_markdown: "Cleanup of the metrics page",
            occurred_at: "2026-05-21T08:00:00Z",
            query_id: "00000000-0000-0000-0000-000000000001",
            net_saved_tokens: 28200,
          },
        ],
      }),
    );
    const result = await callTaskforceSessionLog({ session_id: "s2" });
    expect(result.entries).toHaveLength(1);
    expect(result.entries[0].confidence_band).toBe("high");
    expect(result.entries[0].net_saved_tokens).toBe(28200);
  });

  it("surfaces backend error detail on non-OK", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Unknown session" }, 404),
    );
    await expect(
      callTaskforceSessionLog({ session_id: "missing" }),
    ).rejects.toThrow(/404.*Unknown session/);
  });
});
