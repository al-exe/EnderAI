/**
 * Tier 2 hookless-agent entry points (TF-181).
 *
 * `taskforce_session_start` mints a session_id + runs discovery in one call.
 * `taskforce_session_observe` is a thin pass-through to the existing
 * /observe endpoint with structured fields preferred over a transcript blob
 * (so Codex / Cursor avoid the haiku summarizer cost).
 */

import { enderaiFetch, type ResponseSummary } from "../http.js";

// ----- session_start -------------------------------------------------------

export type TaskforceSessionStartArgs = {
  prompt: string;
  cwd?: string;
  files?: string[];
  git_branch?: string;
  recent_commands?: string[];
  k?: number;
  min_score?: number;
  demo?: boolean;
};

export type TaskforceSessionStartMatch = {
  document_id: string;
  title: string;
  score: number;
  confidence_band: "high" | "medium" | "low";
  match_reasons: string[];
  matched_anchor_id: string | null;
  summary_markdown: string;
  last_touched_at: string | null;
  outcome?: string | null;
  rediscovery_cost_tokens: number;
  consult_token_cost: number;
};

export type TaskforceSessionStartResponse = {
  session_id: string;
  matches: TaskforceSessionStartMatch[];
  suggested_pin: string | null;
  reminder: string;
};

// ----- session_observe -----------------------------------------------------

export type TaskforceTranscriptTurn = {
  role: string;
  content: string;
};

export type TaskforceCommandRun = {
  cmd: string;
  exit_code?: number | null;
};

export type TaskforceHarnessUsage = {
  model_id: string;
  total_input_tokens?: number;
  total_output_tokens?: number;
  total_cache_read_tokens?: number;
  total_cache_write_tokens?: number;
};

export type TaskforceDetailsSectionInput = {
  anchor_id: string;
  markdown: string;
};

export type TaskforceSessionObserveArgs = {
  session_id: string;
  kind: "checkpoint" | "final";
  prompt?: string;
  active_document_id?: string;
  transcript?: TaskforceTranscriptTurn[];
  cwd?: string;
  files_touched?: string[];
  commands_run?: TaskforceCommandRun[];
  diff_summary?: string;
  duration_ms?: number;
  harness?: TaskforceHarnessUsage;
  checkpoint_index?: number;
  // Structured fields — when supplied, the backend skips the haiku
  // summarizer and builds the doc patch directly. Hookless agents
  // should prefer these over shipping a transcript blob.
  summary_points?: string[];
  details_sections?: TaskforceDetailsSectionInput[];
  decisions?: string[];
  outcome?: "shipped" | "blocked" | "paused" | "interrupted";
};

export type TaskforceSessionObserveResponse = {
  action: "created" | "updated" | "skipped";
  document_id: string | null;
  patched_fields: string[];
  reason: string;
  metrics_events_recorded: string[];
  summarizer_usd_cost: string;
  shadow: boolean;
  structured_path: boolean;
};

// ----- shared --------------------------------------------------------------

function asJson<T>(res: ResponseSummary, route: string): T {
  if (!res.ok) {
    const detail =
      typeof res.data === "object" && res.data && "detail" in (res.data as Record<string, unknown>)
        ? String((res.data as Record<string, unknown>).detail)
        : typeof res.data === "string"
          ? res.data
          : `HTTP ${res.status}`;
    throw new Error(`Taskforce ${route} API error ${res.status}: ${detail}`);
  }
  return res.data as T;
}

export async function callTaskforceSessionStart(
  args: TaskforceSessionStartArgs,
  fetchArgs: { bearerToken?: string } = {},
): Promise<TaskforceSessionStartResponse> {
  const res = await enderaiFetch({
    method: "POST",
    path: "/api/v1/v2/taskforce/session/start",
    bearerToken: fetchArgs.bearerToken,
    json: args,
  });
  return asJson<TaskforceSessionStartResponse>(res, "session_start");
}

export async function callTaskforceSessionObserve(
  args: TaskforceSessionObserveArgs,
  fetchArgs: { bearerToken?: string } = {},
): Promise<TaskforceSessionObserveResponse> {
  // The body shape mirrors POST /v2/taskforce/observe exactly.
  const body = {
    kind: args.kind,
    prompt: args.prompt ?? "",
    transcript: args.transcript ?? [],
    active_document_id: args.active_document_id ?? null,
    pinned_query_id: null,
    session_id: args.session_id,
    cwd: args.cwd ?? null,
    files_touched: args.files_touched ?? [],
    commands_run: args.commands_run ?? [],
    diff_summary: args.diff_summary ?? null,
    duration_ms: args.duration_ms ?? 0,
    harness: args.harness ?? null,
    checkpoint_index: args.checkpoint_index ?? null,
    summary_points: args.summary_points ?? [],
    details_sections: args.details_sections ?? [],
    decisions: args.decisions ?? [],
    outcome: args.outcome ?? null,
  };
  const res = await enderaiFetch({
    method: "POST",
    path: "/api/v1/v2/taskforce/observe",
    bearerToken: fetchArgs.bearerToken,
    json: body,
  });
  return asJson<TaskforceSessionObserveResponse>(res, "session_observe");
}
