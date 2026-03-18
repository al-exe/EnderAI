import http from "node:http";
import { randomUUID, webcrypto } from "node:crypto";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createMcpServer } from "../src/mcpServer.js";

if (!(globalThis as any).crypto) {
  (globalThis as any).crypto = webcrypto;
}

const realFetch = globalThis.fetch.bind(globalThis);
const mockFetch = vi.fn();
(globalThis as any).fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url;
  if (url.startsWith("http://127.0.0.1")) {
    return await realFetch(input as any, init);
  }
  return await mockFetch(input, init);
});

type Session = {
  id: string;
  transport: WebStandardStreamableHTTPServerTransport;
  server: ReturnType<typeof createMcpServer>;
};

type Harness = {
  client: Client;
  close: () => Promise<void>;
};

beforeEach(() => {
  mockFetch.mockReset();
  process.env.ENDERAI_BASE_URL = "https://enderai-backend.onrender.com";
  delete process.env.ENDERAI_BEARER_TOKEN;
});

describe("guided case workflow MCP tools", () => {
  it("lists the high-level case workflow tools", async () => {
    const harness = await createHarness();
    try {
      const tools = await harness.client.listTools();
      const names = tools.tools.map((tool) => tool.name);
      expect(names).toEqual(
        expect.arrayContaining([
          "enderai_begin_case",
          "enderai_update_case",
          "enderai_finish_case",
          "enderai_request",
          "enderai_session_info",
          "enderai_openapi",
          "enderai_health_check",
        ]),
      );
    } finally {
      await harness.close();
    }
  });

  it("enforces the begin → update → finish workflow", async () => {
    const harness = await createHarness();
    try {
      const beforeBegin = await harness.client.callTool({
        name: "enderai_update_case",
        arguments: { summary_current: "Should fail before begin" },
      });
      expect(summarizeToolText(beforeBegin.content)).toContain(
        "Run enderai_begin_case first or provide case_id",
      );

      const topicId = "11111111-1111-1111-1111-111111111111";
      const caseId = "22222222-2222-2222-2222-222222222222";

      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            thread: {
              id: topicId,
              title: "Core model",
              workflow_key: "core_model",
              status: "open",
            },
            execution: {
              id: caseId,
              thread_id: topicId,
              status: "running",
              summary: "Hydration gap",
            },
            reused_thread: false,
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            policy: { confidence: "high", max_topics: 1 },
            matched_topics: [],
            selected_topic_ids: [topicId],
            selected_case_ids: [caseId],
            relevant_cases: [
              {
                case_id: caseId,
                title: "Hydration gap",
                short_summary: "Hydration gap",
                outcome: null,
                key_files: [
                  "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
                ],
                key_symbols: [],
                key_errors: [],
                key_commands: [],
                why_selected: "request-text overlap: hydration",
              },
            ],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
              matched_signals: ["hydration gap"],
              representative_cases: [caseId],
              recent_cases: [caseId],
              relevant_cases: [
                {
                  case_id: caseId,
                  title: "Hydration gap",
                  short_summary: "Hydration gap",
                  outcome: null,
                  key_files: [
                    "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
                  ],
                  key_symbols: [],
                  key_errors: [],
                  key_commands: [],
                  why_selected: "request-text overlap: hydration",
                },
              ],
              canonical_files: [
                "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
              ],
              canonical_symbols: [],
              canonical_errors: [],
              canonical_symptoms: [],
              pinned_takeaways: [],
              ambiguities: [],
              questions: [],
              negative_history: [],
              builder_version: "v1",
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            title: "Hydration gap",
            status: "running",
            input_summary: "Hydration gap",
            summary_current: "Hydration gap",
            files: [
              "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
            ],
            symbols: [],
            errors: [],
            symptoms: [],
            commands: [],
            hypotheses: [],
            changes: [],
            next_steps: [],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
            },
          }),
        );

      const begin = await harness.client.callTool({
        name: "enderai_begin_case",
        arguments: {
          topic_title: "Core model",
          workflow_key: "core_model",
          request_summary: "Hydration gap",
          case_title: "Hydration gap",
          files: [
            "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
          ],
        },
      });
      const beginBody = JSON.parse(summarizeToolText(begin.content));
      expect(beginBody.next.case_id).toBe(caseId);
      expect(beginBody.context_pack.context_pack_snapshot.topic_id).toBe(topicId);
      expect(beginBody.hydration.hydration_status).toBe("attached");
      expect(beginBody.hydration.context_pack_attached).toBe(true);
      expect(beginBody.hydration.relevant_case_count).toBe(1);
      expect(mockFetch.mock.calls[0][0].toString()).toContain("/api/v1/executions/start");
      expect(mockFetch.mock.calls[1][0].toString()).toContain("/api/v1/context-packs/build");
      expect(mockFetch.mock.calls[2][0].toString()).toContain(`/api/v1/cases/${caseId}`);
      expect(JSON.parse(mockFetch.mock.calls[1][1].body)).toMatchObject({
        topic_id: topicId,
        request_summary: "Hydration gap",
      });

      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            title: "Hydration gap",
            status: "running",
            input_summary: "Hydration gap",
            summary_current: "Captured first evidence",
            files: ["backend/app/api/routes/cases.py"],
            symbols: [],
            errors: ["missing command history"],
            symptoms: [],
            commands: [],
            hypotheses: [],
            changes: [],
            next_steps: [],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: 1,
            execution_id: caseId,
            type: "mcp_progress",
            message: "Captured first evidence",
          }),
        );

      const update = await harness.client.callTool({
        name: "enderai_update_case",
        arguments: {
          summary_current: "Captured first evidence",
          files: ["backend/app/api/routes/cases.py"],
          errors: ["missing command history"],
          progress_note: "Captured first evidence",
        },
      });
      const updateBody = JSON.parse(summarizeToolText(update.content));
      expect(updateBody.case.summary_current).toBe("Captured first evidence");
      expect(updateBody.progress_event.message).toBe("Captured first evidence");
      expect(mockFetch.mock.calls[3][0].toString()).toContain(`/api/v1/cases/${caseId}`);
      expect(mockFetch.mock.calls[4][0].toString()).toContain(
        `/api/v1/executions/${caseId}/events`,
      );

      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            title: "Hydration gap",
            status: "done",
            input_summary: "Hydration gap",
            summary_current: "Captured first evidence",
            files: ["backend/app/api/routes/cases.py"],
            symbols: [],
            errors: ["missing command history"],
            symptoms: [],
            commands: [],
            hypotheses: [],
            changes: [],
            outcome: "Hydration now carries the right prior context.",
            next_steps: [],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: 2,
            execution_id: caseId,
            type: "mcp_finish",
            message: "Closed the case",
          }),
        );

      const finish = await harness.client.callTool({
        name: "enderai_finish_case",
        arguments: {
          outcome: "Hydration now carries the right prior context.",
          closing_note: "Closed the case",
        },
      });
      const finishBody = JSON.parse(summarizeToolText(finish.content));
      expect(finishBody.case.status).toBe("done");
      expect(finishBody.session_context_cleared).toBe(true);
      expect(finishBody.closing_event.message).toBe("Closed the case");

      const afterFinish = await harness.client.callTool({
        name: "enderai_update_case",
        arguments: { summary_current: "Should fail after finish" },
      });
      expect(summarizeToolText(afterFinish.content)).toContain(
        "Run enderai_begin_case first or provide case_id",
      );
    } finally {
      await harness.close();
    }
  });

  it("blocks write-like enderai_request calls before a case begins", async () => {
    const harness = await createHarness();
    try {
      const beforeBegin = await harness.client.callTool({
        name: "enderai_request",
        arguments: {
          method: "POST",
          path: "/api/v1/artifacts/",
          json: { title: "Should fail" },
        },
      });

      expect(summarizeToolText(beforeBegin.content)).toContain(
        "enderai_request write-like calls require an active case",
      );
      expect(mockFetch).not.toHaveBeenCalled();
    } finally {
      await harness.close();
    }
  });

  it("does not let audit.execution_id bypass the active-case guard", async () => {
    const harness = await createHarness();
    try {
      const beforeBegin = await harness.client.callTool({
        name: "enderai_request",
        arguments: {
          method: "POST",
          path: "/api/v1/artifacts/",
          json: { title: "Should still fail" },
          audit: {
            execution_id: "22222222-2222-2222-2222-222222222222",
          },
        },
      });

      expect(summarizeToolText(beforeBegin.content)).toContain(
        "audit.execution_id does not replace an active case",
      );
      expect(mockFetch).not.toHaveBeenCalled();
    } finally {
      await harness.close();
    }
  });

  it("reports session readiness from ENDERAI_BEARER_TOKEN fallback", async () => {
    process.env.ENDERAI_BEARER_TOKEN = "operator-bearer-token";

    const harness = await createHarness();
    try {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          id: "user-1",
          email: "frontend-test@example.com",
          full_name: "Frontend Test User",
        }),
      );

      const info = await harness.client.callTool({
        name: "enderai_session_info",
        arguments: {},
      });
      const infoBody = JSON.parse(summarizeToolText(info.content));

      expect(infoBody.session_ready).toBe(true);
      expect(infoBody.user).toMatchObject({
        id: "user-1",
        email: "frontend-test@example.com",
        full_name: "Frontend Test User",
      });
      expect(mockFetch.mock.calls[0][0].toString()).toContain("/api/v1/users/me");
      expect(mockFetch.mock.calls[0][1]?.headers).toMatchObject({
        authorization: "Bearer operator-bearer-token",
      });
    } finally {
      await harness.close();
    }
  });
});

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function createHarness(): Promise<Harness> {
  const sessions = new Map<string, Session>();
  const httpServer = http.createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
    if (url.pathname !== "/mcp") {
      res.writeHead(404);
      res.end();
      return;
    }

    const method = (req.method ?? "GET").toUpperCase();
    const sessionId = headerString(req, "mcp-session-id");
    const parsedBody = method === "POST" ? await parseJsonBody(req, res) : undefined;
    if (method === "POST" && parsedBody === undefined) return;

    let session: Session | undefined;
    if (sessionId) {
      session = sessions.get(sessionId);
      if (!session && method === "POST" && containsInitialize(parsedBody)) {
        session = await createSession(sessions, sessionId);
      } else if (!session) {
        res.writeHead(404);
        res.end();
        return;
      }
    } else {
      if (!containsInitialize(parsedBody)) {
        res.writeHead(400);
        res.end("Bad Request: Server not initialized");
        return;
      }
      session = await createSession(sessions);
    }

    try {
      const webReq = nodeRequestToWebRequest(req, url);
      const webRes = await session.transport.handleRequest(webReq, { parsedBody });
      await sendWebResponse(res, webRes);
    } catch (err) {
      if (!res.headersSent) res.writeHead(500);
      res.end(err instanceof Error ? err.stack ?? err.message : String(err));
    }
  });

  await new Promise<void>((resolve) => httpServer.listen(0, "127.0.0.1", resolve));
  const addr = httpServer.address();
  if (!addr || typeof addr === "string") throw new Error("Unexpected address");

  const clientTransport = new StreamableHTTPClientTransport(
    new URL(`http://127.0.0.1:${addr.port}/mcp`),
  );
  const client = new Client({ name: "enderai-api-test", version: "0.0.0" });
  await client.connect(clientTransport);

  return {
    client,
    close: async () => {
      await client.close();
      await Promise.allSettled(
        [...sessions.values()].flatMap((session) => [
          session.transport.close(),
          session.server.close(),
        ]),
      );
      await new Promise<void>((resolve) => httpServer.close(() => resolve()));
    },
  };
}

async function createSession(
  sessions: Map<string, Session>,
  forcedId?: string,
): Promise<Session> {
  const id = forcedId ?? randomUUID();
  const transport = new WebStandardStreamableHTTPServerTransport({
    sessionIdGenerator: () => id,
    enableJsonResponse: true,
    onsessionclosed: async (closedId) => {
      const session = sessions.get(closedId);
      if (!session) return;
      sessions.delete(closedId);
      await Promise.allSettled([session.transport.close(), session.server.close()]);
    },
  });
  const server = createMcpServer();
  await server.connect(transport);
  const session = { id, transport, server };
  sessions.set(id, session);
  return session;
}

function headerString(req: http.IncomingMessage, name: string): string | undefined {
  const value = req.headers[name.toLowerCase()];
  if (!value) return undefined;
  return Array.isArray(value) ? value[0] : value;
}

async function parseJsonBody(
  req: http.IncomingMessage,
  res: http.ServerResponse,
): Promise<unknown | undefined> {
  const chunks: Uint8Array[] = [];
  for await (const chunk of req) {
    chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
  }
  const buf = Buffer.concat(chunks);
  if (buf.length === 0) {
    res.writeHead(400);
    res.end("Parse error: Invalid JSON");
    return undefined;
  }
  try {
    return JSON.parse(buf.toString("utf8"));
  } catch {
    res.writeHead(400);
    res.end("Parse error: Invalid JSON");
    return undefined;
  }
}

function containsInitialize(parsedBody: unknown): boolean {
  if (!parsedBody) return false;
  const messages = Array.isArray(parsedBody) ? parsedBody : [parsedBody];
  return messages.some(
    (message) =>
      message && typeof message === "object" && (message as any).method === "initialize",
  );
}

function nodeRequestToWebRequest(req: http.IncomingMessage, url: URL): Request {
  const headers = new Headers();
  for (const [key, value] of Object.entries(req.headers)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) {
      for (const item of value) headers.append(key, item);
    } else {
      headers.set(key, value);
    }
  }
  const method = (req.method ?? "GET").toUpperCase();
  return new Request(url.toString(), { method, headers });
}

async function sendWebResponse(res: http.ServerResponse, webRes: Response): Promise<void> {
  const headersObj: Record<string, string> = {};
  for (const [key, value] of webRes.headers.entries()) headersObj[key] = value;
  res.writeHead(webRes.status, headersObj);

  if (!webRes.body) {
    res.end();
    return;
  }

  const reader = webRes.body.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) res.write(Buffer.from(value));
    }
  } finally {
    reader.releaseLock();
  }
  res.end();
}

function summarizeToolText(content: unknown): string {
  if (!Array.isArray(content) || content.length === 0) return String(content);
  const first: any = content[0];
  return typeof first?.text === "string" ? first.text : JSON.stringify(first);
}
