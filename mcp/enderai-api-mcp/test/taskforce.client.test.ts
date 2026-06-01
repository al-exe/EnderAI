import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { createMcpServer, type McpServerOptions } from "../src/mcpServer.js";
import { callTaskforceDiscover } from "../src/taskforce/discover.js";
import {
  callTaskforceSessionObserve,
  callTaskforceSessionStart,
} from "../src/taskforce/session.js";

async function connectedClient(opts: McpServerOptions = {}): Promise<Client> {
  const server = createMcpServer(opts);
  const [serverTransport, clientTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  const client = new Client({ name: "test", version: "0" }, { capabilities: {} });
  await client.connect(clientTransport);
  return client;
}

/**
 * TF-203 / C4 — client self-report.
 *
 * Each Taskforce entry point threads a self-reported `client` into the request
 * body so cross-boundary reuse (TF-202 / C3) can attribute the origin +
 * consuming harness. These tests pin the wire contract at both the call-helper
 * level and the MCP dispatch level (per-call arg + server default).
 */

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
  delete process.env.TASKFORCE_CLIENT;
  delete process.env.ENDERAI_CLIENT;
});

afterEach(() => {
  (globalThis as { fetch: typeof realFetch }).fetch = realFetch;
  delete process.env.TASKFORCE_CLIENT;
  delete process.env.ENDERAI_CLIENT;
});

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function lastBody(): Record<string, unknown> {
  const call = mockFetch.mock.calls.at(-1)!;
  const init = call[1] as RequestInit;
  return JSON.parse(init.body as string);
}

describe("client self-report — call helpers", () => {
  it("discover sends client in the request body", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ query_id: "q", matches: [] }));
    await callTaskforceDiscover(
      { prompt: "continue", client: "claude-code" },
      { bearerToken: "tok" },
    );
    expect(lastBody().client).toBe("claude-code");
  });

  it("session_start sends client in the request body", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ session_id: "s", matches: [], suggested_pin: null, reminder: "" }),
    );
    await callTaskforceSessionStart(
      { prompt: "begin", client: "codex" },
      { bearerToken: "tok" },
    );
    expect(lastBody().client).toBe("codex");
  });

  it("session_observe sends client in the request body", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        action: "skipped",
        document_id: null,
        patched_fields: [],
        reason: "shadow",
        metrics_events_recorded: [],
        summarizer_usd_cost: "0",
        shadow: true,
        structured_path: true,
      }),
    );
    await callTaskforceSessionObserve(
      { session_id: "s", kind: "final", client: "cursor" },
      { bearerToken: "tok" },
    );
    expect(lastBody().client).toBe("cursor");
  });
});

describe("client self-report — MCP dispatch", () => {
  it("advertises a client property on discover / session_start / session_observe", async () => {
    const client = await connectedClient();
    const res = await client.listTools();
    for (const toolName of [
      "taskforce_discover",
      "taskforce_session_start",
      "taskforce_session_observe",
    ]) {
      const tool = res.tools.find((t) => t.name === toolName);
      expect(tool, `${toolName} should be listed`).toBeTruthy();
      expect(
        (tool!.inputSchema.properties as Record<string, unknown> | undefined)?.client,
        `${toolName} should advertise a client property`,
      ).toBeTruthy();
    }
  });

  it("a per-call client arg is forwarded to the backend", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ query_id: "q", matches: [] }));
    const client = await connectedClient();
    await client.callTool({
      name: "taskforce_discover",
      arguments: { prompt: "find prior work", client: "claude-code" },
    });
    expect(lastBody().client).toBe("claude-code");
  });

  it("falls back to the server defaultClient when no per-call client is given", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ query_id: "q", matches: [] }));
    const client = await connectedClient({ defaultClient: "codex" });
    await client.callTool({
      name: "taskforce_discover",
      arguments: { prompt: "find prior work" },
    });
    expect(lastBody().client).toBe("codex");
  });

  it("falls back to TASKFORCE_CLIENT env when no arg or option is set", async () => {
    process.env.TASKFORCE_CLIENT = "cursor";
    mockFetch.mockResolvedValueOnce(jsonResponse({ query_id: "q", matches: [] }));
    const client = await connectedClient();
    await client.callTool({
      name: "taskforce_discover",
      arguments: { prompt: "find prior work" },
    });
    expect(lastBody().client).toBe("cursor");
  });
});
