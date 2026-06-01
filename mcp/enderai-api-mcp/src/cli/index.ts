#!/usr/bin/env node
/**
 * taskforce-cli (TF-182 / Phase 8) — Tier 3 entry point for harnesses
 * that don't speak MCP.
 *
 * Wraps the same HTTP endpoints the Tier 1 hooks and Tier 2 MCP tools
 * use. Same auth (`~/.enderai_mcp_token` or `--token`), same JSON I/O.
 *
 * Subcommands:
 *   discover     POST /v2/taskforce/discover
 *   session      POST /v2/taskforce/session/start (alias: start)
 *   observe      POST /v2/taskforce/observe
 *   session-log  GET  /v2/taskforce/session-log
 *
 * Run `taskforce-cli --help` for full usage.
 */

import { readFileSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { resolve as resolvePath } from "node:path";

const VERSION = "0.1.0";

type ParsedArgs = {
  command: string;
  options: Record<string, string | string[] | boolean>;
  positional: string[];
};

function parseArgs(argv: string[]): ParsedArgs {
  const [command, ...rest] = argv;
  const options: Record<string, string | string[] | boolean> = {};
  const positional: string[] = [];

  for (let i = 0; i < rest.length; i++) {
    const arg = rest[i];
    if (arg === "--help" || arg === "-h") {
      options.help = true;
      continue;
    }
    if (arg.startsWith("--")) {
      const key = arg.slice(2);
      // Bool flag if next is missing or also --…; otherwise value.
      const next = rest[i + 1];
      if (next === undefined || next.startsWith("--")) {
        options[key] = true;
      } else {
        if (options[key] && Array.isArray(options[key])) {
          (options[key] as string[]).push(next);
        } else if (options[key]) {
          options[key] = [options[key] as string, next];
        } else {
          options[key] = next;
        }
        i += 1;
      }
    } else {
      positional.push(arg);
    }
  }

  return { command: command ?? "", options, positional };
}

function loadToken(opts: ParsedArgs["options"]): string {
  const explicit = (opts.token as string | undefined) || process.env.TASKFORCE_BEARER_TOKEN || process.env.ENDERAI_BEARER_TOKEN;
  if (explicit && explicit.trim()) return explicit.trim();
  const tokenFile = (opts["token-file"] as string | undefined) || `${homedir()}/.enderai_mcp_token`;
  const resolved = resolvePath(tokenFile);
  if (!existsSync(resolved)) {
    throw new Error(
      `No token. Pass --token, set TASKFORCE_BEARER_TOKEN, or write your MCP token to ${resolved}.`,
    );
  }
  return readFileSync(resolved, "utf8").trim();
}

function backendUrl(opts: ParsedArgs["options"]): string {
  return (
    (opts.backend as string | undefined) ||
    process.env.TASKFORCE_BACKEND_URL ||
    process.env.ENDERAI_BACKEND_URL ||
    "https://enderai-backend.onrender.com"
  );
}

// TF-203 / C4: the harness self-reports its client so cross-boundary reuse
// can attribute the origin + consuming tool. Defaults to "codex" because the
// CLI is the Tier-3 entry point for hookless agents (Codex/Cursor); override
// with --client or TASKFORCE_CLIENT.
function clientOf(opts: ParsedArgs["options"]): string {
  const explicit = opts.client as string | undefined;
  return (
    (explicit && explicit.trim()) ||
    process.env.TASKFORCE_CLIENT?.trim() ||
    process.env.ENDERAI_CLIENT?.trim() ||
    "codex"
  );
}

function readJsonFile(path: string): unknown {
  const resolved = resolvePath(path);
  return JSON.parse(readFileSync(resolved, "utf8"));
}

function readMaybeJsonOrLines(value: string | undefined, file: string | undefined): string[] {
  if (file) {
    const content = readFileSync(resolvePath(file), "utf8");
    try {
      const parsed = JSON.parse(content);
      if (Array.isArray(parsed)) return parsed.map(String);
    } catch {
      // not JSON; fall through to line-split
    }
    return content
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  }
  if (!value) return [];
  // Comma-separated wins over single value.
  if (value.includes(",")) {
    return value
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return [value];
}

async function fetchJson<T>(
  url: string,
  init: RequestInit,
): Promise<{ ok: boolean; status: number; data: T | { detail?: string } }> {
  const res = await fetch(url, init);
  const text = await res.text();
  let data: unknown = text;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* leave as text */
  }
  return { ok: res.ok, status: res.status, data: data as T };
}

function output(value: unknown, opts: ParsedArgs["options"]) {
  const pretty = opts.pretty === true || opts.pretty === "true";
  process.stdout.write(JSON.stringify(value, null, pretty ? 2 : 0) + "\n");
}

function ensureOk(
  res: { ok: boolean; status: number; data: unknown },
  route: string,
): void {
  if (res.ok) return;
  const detail =
    typeof res.data === "object" && res.data && "detail" in (res.data as Record<string, unknown>)
      ? String((res.data as Record<string, unknown>).detail)
      : typeof res.data === "string"
        ? res.data
        : `HTTP ${res.status}`;
  process.stderr.write(`taskforce-cli ${route} failed: ${res.status} ${detail}\n`);
  process.exit(1);
}

// ---------------------------------------------------------------------------

async function cmdDiscover(args: ParsedArgs) {
  if (args.options.help) {
    process.stdout.write(
      `Usage: taskforce-cli discover --prompt "..." [--client NAME] [--cwd PATH] [--files A,B] [--git-branch NAME] [--k 3] [--min-score 0.3] [--demo]\n`,
    );
    return;
  }
  const prompt = args.options.prompt as string | undefined;
  if (!prompt) throw new Error("`discover` requires --prompt");

  const body: Record<string, unknown> = { prompt, client: clientOf(args.options) };
  if (args.options.cwd) body.cwd = args.options.cwd;
  if (args.options["git-branch"]) body.git_branch = args.options["git-branch"];
  if (args.options.files) {
    body.files = readMaybeJsonOrLines(
      args.options.files as string,
      args.options["files-file"] as string | undefined,
    );
  }
  if (args.options.k) body.k = Number(args.options.k);
  if (args.options["min-score"]) body.min_score = Number(args.options["min-score"]);
  if (args.options.demo === true) body.demo = true;

  const res = await fetchJson(`${backendUrl(args.options)}/api/v1/v2/taskforce/discover`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${loadToken(args.options)}`,
    },
    body: JSON.stringify(body),
  });
  ensureOk(res, "discover");
  output(res.data, args.options);
}

async function cmdSessionStart(args: ParsedArgs) {
  if (args.options.help) {
    process.stdout.write(
      `Usage: taskforce-cli session --prompt "..." [--client NAME] [--cwd PATH] [--files A,B] [--k 3] [--min-score 0.3] [--demo]\n`,
    );
    return;
  }
  const prompt = args.options.prompt as string | undefined;
  if (!prompt) throw new Error("`session` requires --prompt");

  const body: Record<string, unknown> = { prompt, client: clientOf(args.options) };
  if (args.options.cwd) body.cwd = args.options.cwd;
  if (args.options["git-branch"]) body.git_branch = args.options["git-branch"];
  if (args.options.files) {
    body.files = readMaybeJsonOrLines(
      args.options.files as string,
      args.options["files-file"] as string | undefined,
    );
  }
  if (args.options.k) body.k = Number(args.options.k);
  if (args.options["min-score"]) body.min_score = Number(args.options["min-score"]);
  if (args.options.demo === true) body.demo = true;

  const res = await fetchJson(`${backendUrl(args.options)}/api/v1/v2/taskforce/session/start`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${loadToken(args.options)}`,
    },
    body: JSON.stringify(body),
  });
  ensureOk(res, "session_start");
  output(res.data, args.options);
}

async function cmdObserve(args: ParsedArgs) {
  if (args.options.help) {
    process.stdout.write(
      `Usage: taskforce-cli observe --session-id ID --kind final|checkpoint
                          [--client NAME]
                          [--active-document-id ID]
                          [--summary-points "a,b" | --summary-points-file FILE]
                          [--decisions "a,b"     | --decisions-file FILE]
                          [--files-touched a,b   | --files-touched-file FILE]
                          [--outcome shipped|blocked|paused|interrupted]
                          [--visibility private|organization]
                          [--details-sections-file FILE]   # JSON array
                          [--harness-file FILE]            # JSON object
                          [--cwd PATH] [--duration-ms N]
\n`,
    );
    return;
  }

  const sessionId = args.options["session-id"] as string | undefined;
  if (!sessionId) throw new Error("`observe` requires --session-id");
  const kind = args.options.kind as string | undefined;
  if (!kind || (kind !== "final" && kind !== "checkpoint")) {
    throw new Error("`observe` requires --kind final|checkpoint");
  }
  const visibility = args.options.visibility as string | undefined;
  if (visibility && visibility !== "private" && visibility !== "organization") {
    throw new Error("`observe` --visibility must be private|organization");
  }

  const body: Record<string, unknown> = {
    session_id: sessionId,
    kind,
    client: clientOf(args.options),
    prompt: (args.options.prompt as string | undefined) || "",
    transcript: [],
    active_document_id: (args.options["active-document-id"] as string | undefined) || null,
    visibility: visibility || "private",
    pinned_query_id: null,
    cwd: (args.options.cwd as string | undefined) || null,
    files_touched: readMaybeJsonOrLines(
      args.options["files-touched"] as string | undefined,
      args.options["files-touched-file"] as string | undefined,
    ),
    commands_run: [],
    diff_summary: null,
    duration_ms: Number(args.options["duration-ms"] || 0),
    harness: args.options["harness-file"]
      ? readJsonFile(args.options["harness-file"] as string)
      : null,
    checkpoint_index: args.options["checkpoint-index"]
      ? Number(args.options["checkpoint-index"])
      : null,
    summary_points: readMaybeJsonOrLines(
      args.options["summary-points"] as string | undefined,
      args.options["summary-points-file"] as string | undefined,
    ),
    details_sections: args.options["details-sections-file"]
      ? readJsonFile(args.options["details-sections-file"] as string)
      : [],
    decisions: readMaybeJsonOrLines(
      args.options.decisions as string | undefined,
      args.options["decisions-file"] as string | undefined,
    ),
    outcome: (args.options.outcome as string | undefined) || null,
  };

  const res = await fetchJson(`${backendUrl(args.options)}/api/v1/v2/taskforce/observe`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${loadToken(args.options)}`,
    },
    body: JSON.stringify(body),
  });
  ensureOk(res, "observe");
  output(res.data, args.options);
}

async function cmdSessionLog(args: ParsedArgs) {
  if (args.options.help) {
    process.stdout.write(
      `Usage: taskforce-cli session-log --session-id ID [--limit 50]\n`,
    );
    return;
  }
  const sessionId = args.options["session-id"] as string | undefined;
  if (!sessionId) throw new Error("`session-log` requires --session-id");

  const url = new URL(`${backendUrl(args.options)}/api/v1/v2/taskforce/session-log`);
  url.searchParams.set("session_id", sessionId);
  if (args.options.limit) url.searchParams.set("limit", String(args.options.limit));

  const res = await fetchJson(url.toString(), {
    method: "GET",
    headers: { Authorization: `Bearer ${loadToken(args.options)}` },
  });
  ensureOk(res, "session-log");
  output(res.data, args.options);
}

function printHelp() {
  process.stdout.write(
    `taskforce-cli v${VERSION}

Tier 3 entry point for harnesses without MCP support. Same auth as
the hooks (~/.enderai_mcp_token by default).

Subcommands:
  discover      Search the library for related prior work.
  session       Mint a session_id + run discovery (Tier 2 entry point).
  observe       Record session progress / completion.
  session-log   Show the consult history for a session.

Global options (any subcommand):
  --token VALUE         Bearer token (overrides TASKFORCE_BEARER_TOKEN env).
  --token-file PATH     Token file (defaults to ~/.enderai_mcp_token).
  --backend URL         Backend URL (defaults to enderai-backend.onrender.com).
  --client NAME         Self-reported harness/client (default: codex; also
                        TASKFORCE_CLIENT env). Drives cross-boundary reuse
                        attribution (TF-202/C3).
  --pretty              Pretty-print JSON output.
  --help                Subcommand-specific usage.

Examples:
  taskforce-cli discover --prompt "fix metrics card" --cwd $PWD --pretty
  taskforce-cli session  --prompt "library polish" --client codex --pretty
  taskforce-cli observe  --session-id 0000-…-0001 --kind final \\
    --active-document-id 1111-…-1111 \\
    --summary-points "Did the thing,Then did the other" \\
    --outcome shipped
  taskforce-cli session-log --session-id 0000-…-0001 --pretty
`,
  );
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv.length === 0 || argv[0] === "--help" || argv[0] === "-h" || argv[0] === "help") {
    printHelp();
    return;
  }
  if (argv[0] === "--version" || argv[0] === "-V") {
    process.stdout.write(`${VERSION}\n`);
    return;
  }

  const parsed = parseArgs(argv);

  try {
    switch (parsed.command) {
      case "discover":
        await cmdDiscover(parsed);
        return;
      case "session":
      case "start":
      case "session-start":
        await cmdSessionStart(parsed);
        return;
      case "observe":
        await cmdObserve(parsed);
        return;
      case "session-log":
      case "log":
        await cmdSessionLog(parsed);
        return;
      default:
        process.stderr.write(`Unknown subcommand: ${parsed.command}\n\n`);
        printHelp();
        process.exit(2);
    }
  } catch (err) {
    process.stderr.write(
      `taskforce-cli: ${err instanceof Error ? err.message : String(err)}\n`,
    );
    process.exit(1);
  }
}

main();
