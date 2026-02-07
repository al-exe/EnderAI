import http from "node:http";
import { randomUUID, webcrypto } from "node:crypto";

import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";

import { createMcpServer } from "./mcpServer.js";

// The MCP SDK's Streamable HTTP implementation expects a global `crypto` with `randomUUID()`.
// Some Node runtimes (and some TS loaders) do not expose `globalThis.crypto` by default.
if (!(globalThis as any).crypto) {
  (globalThis as any).crypto = webcrypto;
}

type Session = {
  id: string;
  transport: WebStandardStreamableHTTPServerTransport;
  server: ReturnType<typeof createMcpServer>;
  createdAtMs: number;
  lastUsedAtMs: number;
};

const sessions = new Map<string, Session>();

function getEnv(name: string): string | undefined {
  const v = process.env[name];
  if (v === undefined) return undefined;
  const t = v.trim();
  return t.length ? t : undefined;
}

function readBearer(req: http.IncomingMessage): string | undefined {
  const h = req.headers.authorization;
  if (!h) return undefined;
  const m = /^Bearer\s+(.+)$/.exec(h);
  return m?.[1]?.trim() || undefined;
}

function getHeaderString(
  req: http.IncomingMessage,
  name: string,
): string | undefined {
  const v = req.headers[name.toLowerCase()];
  if (!v) return undefined;
  return Array.isArray(v) ? v[0] : v;
}

async function main(): Promise<void> {
  const port = Number.parseInt(getEnv("PORT") ?? "8080", 10);
  if (!Number.isFinite(port) || port <= 0) throw new Error(`Invalid PORT: ${port}`);

  const mcpPath = getEnv("MCP_PATH") ?? "/mcp";
  const mcpBearerToken = getEnv("MCP_BEARER_TOKEN"); // strongly recommended for public deploys

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);

    if (url.pathname === "/health") {
      res.writeHead(200, { "content-type": "text/plain" });
      res.end("ok");
      return;
    }

    // Be lenient about a trailing slash.
    const mcpPathWithSlash = mcpPath.endsWith("/") ? mcpPath : `${mcpPath}/`;
    if (url.pathname !== mcpPath && url.pathname !== mcpPathWithSlash) {
      res.writeHead(404, { "content-type": "text/plain" });
      res.end("Not Found");
      return;
    }

    if (mcpBearerToken) {
      const got = readBearer(req);
      if (!got || got !== mcpBearerToken) {
        res.writeHead(401, { "content-type": "text/plain" });
        res.end("Unauthorized");
        return;
      }
    }

    const sessionIdHeader = getHeaderString(req, "mcp-session-id");

    // POST is the only method that can create a session (via initialize).
    // GET/DELETE must include an existing session id.
    const method = (req.method ?? "GET").toUpperCase();
    if (!sessionIdHeader && method !== "POST") {
      res.writeHead(400, { "content-type": "text/plain" });
      res.end("Bad Request: Mcp-Session-Id header is required");
      return;
    }

    if (sessionIdHeader) assertValidSessionId(sessionIdHeader);

    const parsedBody =
      method === "POST" ? await tryParseJsonBody(req, res) : undefined;
    if (method === "POST" && parsedBody === undefined) {
      // tryParseJsonBody already wrote the response.
      return;
    }

    // Determine session routing.
    const isInitialize = method === "POST" && containsInitialize(parsedBody);
    let session = sessionIdHeader ? sessions.get(sessionIdHeader) : undefined;
    let createdSession = false;

    if (!session) {
      // Some clients (Cursor) send Mcp-Session-Id even on the initial initialize.
      // Allow creating the session in that case.
      if (isInitialize) {
        session = await createSession(sessionIdHeader);
        createdSession = true;
      } else if (sessionIdHeader) {
        res.writeHead(404, { "content-type": "text/plain" });
        res.end("Not Found");
        return;
      } else {
        res.writeHead(400, { "content-type": "text/plain" });
        res.end("Bad Request: Server not initialized");
        return;
      }
    }

    session.lastUsedAtMs = Date.now();

    try {
      const webReq = nodeRequestToWebRequest(req, url);
      const webRes = await session.transport.handleRequest(webReq, { parsedBody });
      await sendWebResponse(res, webRes);

      // Persist only after a successful initialize request (avoid leaking sessions).
      if (createdSession && webRes.ok) {
        sessions.set(session.id, session);
      } else if (createdSession && !webRes.ok) {
        await Promise.allSettled([session.transport.close(), session.server.close()]);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (!res.headersSent) res.writeHead(500, { "content-type": "text/plain" });
      res.end(msg);

      // If this was a just-created session that failed init, don't leak resources.
      if (createdSession) {
        await Promise.allSettled([session.transport.close(), session.server.close()]);
      }
    }
  });

  const shutdown = async () => {
    const closers: Promise<unknown>[] = [new Promise<void>((resolve) => server.close(() => resolve()))];
    for (const s of sessions.values()) {
      closers.push(s.transport.close(), s.server.close());
    }
    await Promise.allSettled(closers);
  };

  process.once("SIGINT", () => void shutdown());
  process.once("SIGTERM", () => void shutdown());

  await new Promise<void>((resolve) => server.listen(port, "0.0.0.0", resolve));
  // eslint-disable-next-line no-console
  console.log(`MCP streamable HTTP server listening on :${port}${mcpPath}`);
}

function assertValidSessionId(id: string): void {
  // Header comes from untrusted clients. Keep this permissive but safe.
  if (id.length > 256) throw new Error("Invalid Mcp-Session-Id: too long");
  if (/[\u0000-\u001f\u007f]/.test(id)) throw new Error("Invalid Mcp-Session-Id");
}

async function createSession(forcedId?: string): Promise<Session> {
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

  const now = Date.now();
  return { id, transport, server, createdAtMs: now, lastUsedAtMs: now };
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

async function tryParseJsonBody(
  req: http.IncomingMessage,
  res: http.ServerResponse,
): Promise<unknown | undefined> {
  const chunks: Uint8Array[] = [];
  for await (const chunk of req) {
    chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
  }
  const buf = Buffer.concat(chunks);
  if (buf.length === 0) {
    res.writeHead(400, { "content-type": "text/plain" });
    res.end("Parse error: Invalid JSON");
    return undefined;
  }
  try {
    return JSON.parse(buf.toString("utf8"));
  } catch {
    res.writeHead(400, { "content-type": "text/plain" });
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
