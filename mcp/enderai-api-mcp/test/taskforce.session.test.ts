import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  callTaskforceSessionObserve,
  callTaskforceSessionStart,
} from "../src/taskforce/session.js";

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

describe("callTaskforceSessionStart", () => {
  it("POSTs the session/start endpoint and returns the envelope", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        session_id: "00000000-0000-0000-0000-000000000001",
        matches: [
          {
            document_id: "11111111-1111-1111-1111-111111111111",
            title: "TF-156 polish",
            score: 0.74,
            confidence_band: "high",
            match_reasons: ["Title overlap"],
            matched_anchor_id: "summary",
            summary_markdown: "Cleanup",
            last_touched_at: "2026-05-21T08:00:00Z",
            outcome: null,
            rediscovery_cost_tokens: 17000,
            consult_token_cost: 120,
          },
        ],
        suggested_pin: "11111111-1111-1111-1111-111111111111",
        reminder: "Call observe later.",
      }),
    );

    const result = await callTaskforceSessionStart(
      { prompt: "library polish" },
      { bearerToken: "tok" },
    );

    expect(result.session_id).toBe("00000000-0000-0000-0000-000000000001");
    expect(result.suggested_pin).toBe("11111111-1111-1111-1111-111111111111");
    expect(result.matches).toHaveLength(1);
    expect(result.matches[0].matched_anchor_id).toBe("summary");

    const call = mockFetch.mock.calls[0];
    expect(String(call[0])).toContain("/api/v1/v2/taskforce/session/start");
    expect((call[1] as RequestInit).method).toBe("POST");
    expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({
      prompt: "library polish",
    });
  });

  it("surfaces backend error detail on non-OK", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Authentication required" }, 401),
    );
    await expect(
      callTaskforceSessionStart({ prompt: "hi" }),
    ).rejects.toThrow(/session_start.*401.*Authentication required/);
  });
});

describe("callTaskforceSessionObserve", () => {
  it("hits /observe with the structured-fields payload", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        action: "updated",
        document_id: "11111111-1111-1111-1111-111111111111",
        patched_fields: ["ai_generated_summary", "main_body"],
        reason: "ok",
        metrics_events_recorded: [],
        summarizer_usd_cost: "0",
        shadow: false,
        structured_path: true,
      }),
    );

    const result = await callTaskforceSessionObserve(
      {
        session_id: "00000000-0000-0000-0000-000000000001",
        kind: "final",
        active_document_id: "11111111-1111-1111-1111-111111111111",
        visibility: "organization",
        summary_points: ["Removed lock badge", "Stopped click propagation"],
        decisions: ["Use stopPropagation handler"],
        files_touched: ["src/routes/v2/library.tsx"],
        outcome: "shipped",
        harness: {
          model_id: "gpt-5-codex",
          total_input_tokens: 12000,
          total_output_tokens: 4000,
        },
      },
      { bearerToken: "tok" },
    );

    expect(result.action).toBe("updated");
    expect(result.structured_path).toBe(true);
    expect(result.summarizer_usd_cost).toBe("0");

    const call = mockFetch.mock.calls[0];
    expect(String(call[0])).toContain("/api/v1/v2/taskforce/observe");
    const body = JSON.parse(String((call[1] as RequestInit).body));
    expect(body.kind).toBe("final");
    expect(body.summary_points).toEqual([
      "Removed lock badge",
      "Stopped click propagation",
    ]);
    expect(body.decisions).toEqual(["Use stopPropagation handler"]);
    expect(body.outcome).toBe("shipped");
    expect(body.visibility).toBe("organization");
    expect(body.transcript).toEqual([]);
    expect(body.harness.model_id).toBe("gpt-5-codex");
  });

  it("supplies safe defaults when only required args are passed", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        action: "skipped",
        document_id: null,
        patched_fields: [],
        reason: "trivial session",
        metrics_events_recorded: [],
        summarizer_usd_cost: "0",
        shadow: true,
        structured_path: false,
      }),
    );

    await callTaskforceSessionObserve({
      session_id: "00000000-0000-0000-0000-000000000001",
      kind: "checkpoint",
    });

    const body = JSON.parse(String(mockFetch.mock.calls[0][1].body as string));
    expect(body.summary_points).toEqual([]);
    expect(body.details_sections).toEqual([]);
    expect(body.decisions).toEqual([]);
    expect(body.outcome).toBeNull();
  });
});
