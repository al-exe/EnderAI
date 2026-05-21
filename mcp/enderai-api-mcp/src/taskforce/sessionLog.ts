/**
 * Thin client for the per-session consult log (TF-176).
 *
 * Backs the `/taskforce` slash command — agents can ask "what did the
 * hook pull into context this session?" without leaving Claude Code.
 */

import { enderaiFetch, type ResponseSummary } from "../http.js";

export type TaskforceSessionLogEntry = {
  document_id: string;
  title: string;
  score: number;
  confidence_band: "high" | "medium" | "low";
  match_reasons: string[];
  summary_markdown: string;
  occurred_at: string;
  query_id: string;
  net_saved_tokens: number;
};

export type TaskforceSessionLogResponse = {
  session_id: string;
  entries: TaskforceSessionLogEntry[];
};

export type TaskforceSessionLogArgs = {
  session_id: string;
  limit?: number;
};

function asJson<T>(res: ResponseSummary): T {
  if (!res.ok) {
    const detail =
      typeof res.data === "object" && res.data && "detail" in (res.data as Record<string, unknown>)
        ? String((res.data as Record<string, unknown>).detail)
        : typeof res.data === "string"
          ? res.data
          : `HTTP ${res.status}`;
    throw new Error(`Taskforce session-log API error ${res.status}: ${detail}`);
  }
  return res.data as T;
}

export async function callTaskforceSessionLog(
  args: TaskforceSessionLogArgs,
  fetchArgs: { bearerToken?: string } = {},
): Promise<TaskforceSessionLogResponse> {
  const query: Record<string, unknown> = { session_id: args.session_id };
  if (args.limit !== undefined) query.limit = args.limit;
  const res = await enderaiFetch({
    method: "GET",
    path: "/api/v1/v2/taskforce/session-log",
    query,
    bearerToken: fetchArgs.bearerToken,
  });
  return asJson<TaskforceSessionLogResponse>(res);
}
