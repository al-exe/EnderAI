import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  beginDocument,
  createActiveDocumentState,
  finishDocument,
  updateDocument,
} from "../src/v2Documents/index.js";
import type { V2Document } from "../src/v2Documents/types.js";

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

function makeDoc(partial: Partial<V2Document> = {}): V2Document {
  const now = new Date().toISOString();
  return {
    id: "11111111-1111-1111-1111-111111111111",
    title: "Latest Stale Network Bridge Issue",
    description: "Customer-impact investigation",
    human_summary: "Stale bridge routing after deploy.",
    ai_generated_summary: "Bridge routing summary.",
    collaborators: ["Alex Lee"],
    main_body: [
      {
        segments: [
          {
            text: "Active request: investigate stale bridge",
            evidence_anchor_id: "request",
          },
        ],
      },
    ],
    details_file_name: "bridge.details.md",
    details_markdown_sections: [
      { anchor_id: "request", markdown: "## Request" },
    ],
    is_demo: false,
    created_at: now,
    updated_at: now,
    ...partial,
  };
}

function fetchCalls(): Array<{ method: string; url: string; body: unknown }> {
  return mockFetch.mock.calls.map(([input, init]) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : (input as Request).url;
    const method = String(init?.method ?? "GET").toUpperCase();
    const rawBody = init?.body;
    let body: unknown = rawBody;
    if (typeof rawBody === "string") {
      try {
        body = JSON.parse(rawBody);
      } catch {
        body = rawBody;
      }
    }
    return { method, url, body };
  });
}

describe("beginDocument", () => {
  it("creates a new document when no candidate matches", async () => {
    const state = createActiveDocumentState();
    const created = makeDoc({
      id: "22222222-2222-2222-2222-222222222222",
      title: "Frontend rendering glitch",
    });
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ data: [], count: 0 }))
      .mockResolvedValueOnce(jsonResponse(created));

    const result = await beginDocument(
      {
        request_summary: "Investigate flaky frontend rendering",
        title: "Frontend rendering glitch",
        files: ["src/components/Foo.tsx"],
      },
      { state },
    );

    expect(result.reused_existing).toBe(false);
    expect(result.match_confidence).toBe("low");
    expect(result.document_id).toBe(created.id);
    expect(state.documentId).toBe(created.id);
    const calls = fetchCalls();
    expect(calls[0]).toMatchObject({ method: "GET", url: expect.stringContaining("/v2/documents/") });
    expect(calls[1]).toMatchObject({ method: "POST" });
  });

  it("reuses + self-heals a strong candidate", async () => {
    const state = createActiveDocumentState();
    const candidate = makeDoc({
      description: "",
      details_markdown_sections: [
        {
          anchor_id: "files",
          markdown:
            "Files: `infra/network/bridge-refresh.sh`, `ops/runbooks/bridge.md`. Bridge timeout under load.",
        },
      ],
    });
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ data: [candidate], count: 1 }))
      .mockResolvedValueOnce(jsonResponse(candidate))
      .mockResolvedValueOnce(
        jsonResponse({ ...candidate, description: "fix tenant bridge cache" }),
      );

    const result = await beginDocument(
      {
        request_summary: "continuing the stale bridge routing investigation",
        title: candidate.title,
        goal: "fix tenant bridge cache",
        files: ["infra/network/bridge-refresh.sh", "ops/runbooks/bridge.md"],
        errors: ["timeout"],
      },
      { state },
    );

    expect(result.reused_existing).toBe(true);
    expect(result.match_confidence).not.toBe("low");
    expect(result.self_healed_fields).toContain("populated missing description");
    expect(state.documentId).toBe(candidate.id);
    const calls = fetchCalls();
    expect(calls[0].method).toBe("GET");
    expect(calls[1].method).toBe("GET");
    expect(calls[2].method).toBe("PATCH");
  });

  it("honors document_id even when scoring would prefer create", async () => {
    const state = createActiveDocumentState();
    const candidate = makeDoc();
    mockFetch
      .mockResolvedValueOnce(jsonResponse(candidate))
      .mockResolvedValueOnce(jsonResponse(candidate));

    const result = await beginDocument(
      {
        request_summary: "totally unrelated request",
        document_id: candidate.id,
      },
      { state },
    );
    expect(result.reused_existing).toBe(true);
    expect(result.match_confidence).toBe("explicit");
    expect(fetchCalls()[0].method).toBe("GET");
  });

  it("creates fresh on force_new even when a perfect match exists", async () => {
    const state = createActiveDocumentState();
    const candidate = makeDoc();
    const created = makeDoc({ id: "33333333-3333-3333-3333-333333333333" });
    mockFetch.mockResolvedValueOnce(jsonResponse(created));

    const result = await beginDocument(
      {
        request_summary: candidate.title,
        title: candidate.title,
        force_new: true,
      },
      { state },
    );
    expect(result.reused_existing).toBe(false);
    expect(result.match_confidence).toBe("forced-new");
    // No list call when force_new is set.
    expect(fetchCalls().map((c) => c.method)).toEqual(["POST"]);
  });
});

describe("updateDocument", () => {
  it("requires an active document or document_id", async () => {
    const state = createActiveDocumentState();
    await expect(
      updateDocument({ progress_note: "no doc" }, { state }),
    ).rejects.toThrow(/active document/);
  });

  it("appends a working-log section and merges collaborators", async () => {
    const state = createActiveDocumentState();
    const doc = makeDoc();
    state.documentId = doc.id;
    const patched = { ...doc, collaborators: ["Alex Lee", "Nia Patel"] };
    mockFetch
      .mockResolvedValueOnce(jsonResponse(doc))
      .mockResolvedValueOnce(jsonResponse(patched));

    const result = await updateDocument(
      {
        progress_note: "Refreshed bridge cache",
        commands: [{ cmd: "./infra/network/bridge-refresh.sh", purpose: "refresh" }],
        collaborators: ["Nia Patel"],
      },
      { state },
    );
    expect(result.patched_fields).toEqual(
      expect.arrayContaining([
        "collaborators",
        "details_markdown_sections (working log)",
      ]),
    );
    const calls = fetchCalls();
    expect(calls[1].method).toBe("PATCH");
    const body = calls[1].body as Record<string, unknown>;
    expect(body.collaborators).toEqual(["Alex Lee", "Nia Patel"]);
    expect(Array.isArray(body.details_markdown_sections)).toBe(true);
  });

  it("preserves human_summary unless explicitly set", async () => {
    const state = createActiveDocumentState();
    const doc = makeDoc({ human_summary: "Human-authored." });
    state.documentId = doc.id;
    mockFetch
      .mockResolvedValueOnce(jsonResponse(doc))
      .mockResolvedValueOnce(jsonResponse(doc));

    await updateDocument(
      { progress_note: "Working log only" },
      { state },
    );
    const body = fetchCalls()[1].body as Record<string, unknown>;
    expect(body.human_summary).toBeUndefined();
  });

  it("rejects no-op updates", async () => {
    const state = createActiveDocumentState();
    state.documentId = "11111111-1111-1111-1111-111111111111";
    mockFetch.mockResolvedValueOnce(jsonResponse(makeDoc()));
    await expect(updateDocument({}, { state })).rejects.toThrow(/no changes/);
  });
});

describe("finishDocument", () => {
  it("appends an Outcome section and clears active state", async () => {
    const state = createActiveDocumentState();
    const doc = makeDoc();
    state.documentId = doc.id;
    state.title = doc.title;
    mockFetch
      .mockResolvedValueOnce(jsonResponse(doc))
      .mockResolvedValueOnce(jsonResponse(doc));

    const result = await finishDocument(
      {
        outcome: "Tenant bridge cache refreshed.",
        validation: ["bridge-health probe passed"],
        follow_ups: ["Move script into rollout"],
        status: "done",
      },
      { state },
    );
    expect(result.status).toBe("done");
    expect(state.documentId).toBeUndefined();
    const body = fetchCalls()[1].body as Record<string, unknown>;
    const sections = body.details_markdown_sections as Array<{
      anchor_id: string;
      markdown: string;
    }>;
    const outcome = sections.find((s) => s.anchor_id === "outcome");
    expect(outcome?.markdown).toMatch(/status: done/);
    expect(outcome?.markdown).toMatch(/Tenant bridge cache refreshed/);
  });
});
