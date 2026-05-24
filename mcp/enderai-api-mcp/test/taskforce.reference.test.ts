import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { callTaskforceReference } from "../src/taskforce/reference.js";

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

describe("callTaskforceReference", () => {
  it("POSTs referenced document ids and returns the update envelope", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        updated_document_ids: ["11111111-1111-1111-1111-111111111111"],
        skipped_document_ids: ["22222222-2222-2222-2222-222222222222"],
      }),
    );

    const result = await callTaskforceReference(
      {
        session_id: "00000000-0000-0000-0000-000000000001",
        document_ids: [
          "11111111-1111-1111-1111-111111111111",
          "22222222-2222-2222-2222-222222222222",
        ],
        user_prompt: "continue the metrics polish",
        occurred_at: "2026-05-23T19:00:00Z",
        demo: true,
      },
      { bearerToken: "tok" },
    );

    expect(result.updated_document_ids).toEqual([
      "11111111-1111-1111-1111-111111111111",
    ]);
    expect(result.skipped_document_ids).toEqual([
      "22222222-2222-2222-2222-222222222222",
    ]);

    const call = mockFetch.mock.calls[0];
    expect(String(call[0])).toContain("/api/v1/v2/taskforce/reference");
    expect(String(call[0])).toContain("demo=true");
    expect((call[1] as RequestInit).method).toBe("POST");
    expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({
      session_id: "00000000-0000-0000-0000-000000000001",
      document_ids: [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
      ],
      user_prompt: "continue the metrics polish",
      occurred_at: "2026-05-23T19:00:00Z",
    });
  });

  it("surfaces backend error detail on non-OK", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: "Invalid body" }, 422));
    await expect(
      callTaskforceReference({
        session_id: "00000000-0000-0000-0000-000000000001",
        document_ids: [],
        user_prompt: "hi",
      }),
    ).rejects.toThrow(/reference.*422.*Invalid body/);
  });
});
