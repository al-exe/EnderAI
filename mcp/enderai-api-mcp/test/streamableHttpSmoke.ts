import http from "node:http";
import { randomUUID, webcrypto } from "node:crypto";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";

import { createMcpServer } from "../src/mcpServer.js";
import {
  assertRequiredHookRoutes,
  assertRequiredToolNames,
  parseToolTextJson,
  summarizeToolText,
} from "./hookHealth.js";

// Some Node runtimes (and some TS loaders) do not expose `globalThis.crypto` by default.
if (!(globalThis as any).crypto) {
  (globalThis as any).crypto = webcrypto;
}

type Session = {
  id: string;
  transport: WebStandardStreamableHTTPServerTransport;
  server: ReturnType<typeof createMcpServer>;
};

async function main(): Promise<void> {
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
      // Allow initialize to create a session even when the client pre-sends a session id.
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
  const baseUrl = `http://127.0.0.1:${addr.port}/mcp`;

  const clientTransport = new StreamableHTTPClientTransport(new URL(baseUrl));
  const client = new Client({ name: "enderai-api-streamable-smoke", version: "0.0.0" });
  await client.connect(clientTransport);

  const tools = await client.listTools();
  const toolNames = tools.tools.map((t) => t.name).sort();
  assertRequiredToolNames(toolNames);
  // eslint-disable-next-line no-console
  console.log("tools:", toolNames.join(", "));

  const health = await client.callTool({ name: "enderai_health_check", arguments: {} });
  const healthPayload = parseToolTextJson<any>(health.content);
  if (!healthPayload?.ok) {
    throw new Error(`enderai_health_check failed: ${summarizeToolText(health.content)}`);
  }
  // eslint-disable-next-line no-console
  console.log("enderai_health_check:", summarizeToolText(health.content));

  const openapi = await client.callTool({ name: "enderai_openapi", arguments: {} });
  const openapiPayload = parseToolTextJson<any>(openapi.content);
  assertRequiredHookRoutes(openapiPayload);
  // eslint-disable-next-line no-console
  console.log("enderai_openapi:", summarizeToolText(openapi.content));

  await client.close();

  // Cleanup
  await Promise.allSettled(
    [...sessions.values()].flatMap((s) => [s.transport.close(), s.server.close()]),
  );
  await new Promise<void>((resolve) => httpServer.close(() => resolve()));
}

async function createSession(sessions: Map<string, Session>, forcedId?: string): Promise<Session> {
  const id = forcedId ?? randomUUID();
  const transport = new WebStandardStreamableHTTPServerTransport({
    sessionIdGenerator: () => id,
    enableJsonResponse: true,
    onsessionclosed: async (closedId) => {
      const s = sessions.get(closedId);
      if (!s) return;
      sessions.delete(closedId);
      await Promise.allSettled([s.transport.close(), s.server.close()]);
    },
  });
  const server = createMcpServer();
  await server.connect(transport);
  const session = { id, transport, server };
  sessions.set(id, session);
  return session;
}

function headerString(req: http.IncomingMessage, name: string): string | undefined {
  const v = req.headers[name.toLowerCase()];
  if (!v) return undefined;
  return Array.isArray(v) ? v[0] : v;
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
  const msgs = Array.isArray(parsedBody) ? parsedBody : [parsedBody];
  for (const m of msgs) {
    if (m && typeof m === "object" && (m as any).method === "initialize") return true;
  }
  return false;
}

function nodeRequestToWebRequest(req: http.IncomingMessage, url: URL): Request {
  const headers = new Headers();
  for (const [k, v] of Object.entries(req.headers)) {
    if (v === undefined) continue;
    if (Array.isArray(v)) {
      for (const item of v) headers.append(k, item);
    } else {
      headers.set(k, v);
    }
  }
  const method = (req.method ?? "GET").toUpperCase();
  return new Request(url.toString(), { method, headers });
}

async function sendWebResponse(res: http.ServerResponse, webRes: Response): Promise<void> {
  const headersObj: Record<string, string> = {};
  for (const [k, v] of webRes.headers.entries()) headersObj[k] = v;
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

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error(err);
  process.exit(1);
});
