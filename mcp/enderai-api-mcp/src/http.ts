import { loadConfig } from "./config.js";

export type RequestArgs = {
  method: string;
  path: string;
  query?: Record<string, unknown>;
  headers?: Record<string, string>;
  json?: unknown;
  text?: string;
  bearerToken?: string;
  timeoutMs?: number;
};

export type ResponseSummary = {
  url: string;
  status: number;
  ok: boolean;
  contentType?: string;
  data: unknown;
};

function assertPathIsSafe(path: string): void {
  // Prevent SSRF-ish full URL overrides (new URL("https://x", base) ignores base).
  if (!path.startsWith("/")) {
    throw new Error(`"path" must start with "/". Received: ${path}`);
  }
  if (path.startsWith("//")) {
    throw new Error(`"path" must not start with "//". Received: ${path}`);
  }
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(path)) {
    throw new Error(`"path" must not include a scheme. Received: ${path}`);
  }
}

function withQuery(url: URL, query?: Record<string, unknown>): void {
  if (!query) return;
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null) continue;
    if (Array.isArray(v)) {
      for (const item of v) {
        if (item === undefined || item === null) continue;
        url.searchParams.append(k, String(item));
      }
      continue;
    }
    url.searchParams.set(k, String(v));
  }
}

export async function enderaiFetch(args: RequestArgs): Promise<ResponseSummary> {
  const cfg = loadConfig();
  assertPathIsSafe(args.path);

  const url = new URL(args.path, cfg.baseUrl);
  withQuery(url, args.query);

  const method = args.method.toUpperCase();
  const headers: Record<string, string> = {
    accept: "application/json, text/plain;q=0.9, */*;q=0.1",
    ...(args.headers ?? {}),
  };

  const bearerToken = args.bearerToken ?? cfg.bearerToken;
  if (bearerToken && !("authorization" in lowerKeys(headers))) {
    headers.authorization = `Bearer ${bearerToken}`;
  }

  let body: BodyInit | undefined;
  if (args.json !== undefined && args.text !== undefined) {
    throw new Error('Provide only one of "json" or "text".');
  }
  if (args.json !== undefined) {
    if (!("content-type" in lowerKeys(headers))) {
      headers["content-type"] = "application/json";
    }
    body = JSON.stringify(args.json);
  } else if (args.text !== undefined) {
    body = args.text;
  }

  const controller = new AbortController();
  const timeoutMs = args.timeoutMs ?? cfg.timeoutMs;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method,
      headers,
      body,
      signal: controller.signal,
    });

    const contentType = res.headers.get("content-type") ?? undefined;
    const isJson = contentType?.includes("application/json") ?? false;

    let data: unknown;
    if (isJson) {
      data = await res.json().catch(async () => await res.text());
    } else {
      data = await res.text();
    }

    return {
      url: url.toString(),
      status: res.status,
      ok: res.ok,
      contentType,
      data,
    };
  } finally {
    clearTimeout(timer);
  }
}

function lowerKeys(obj: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(obj)) out[k.toLowerCase()] = v;
  return out;
}

