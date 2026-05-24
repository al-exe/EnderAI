/**
 * Thin client + handler for the Taskforce hook-driven discover endpoint
 * (TF-175 / TF-174 epic). The MCP tool is mostly a fallback for harnesses
 * without hook support — the canonical caller is the UserPromptSubmit hook
 * (TF-176), which hits the backend HTTP endpoint directly.
 */

import { enderaiFetch, type ResponseSummary } from "../http.js";

export type TaskforceDiscoverArgs = {
  prompt: string;
  cwd?: string;
  files?: string[];
  git_branch?: string;
  recent_commands?: string[];
  k?: number;
  min_score?: number;
  demo?: boolean;
};

export type TaskforceDiscoverMatch = {
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

export type TaskforceDiscoverResponse = {
  query_id: string;
  matches: TaskforceDiscoverMatch[];
};

function asJson<T>(res: ResponseSummary): T {
  if (!res.ok) {
    const detail =
      typeof res.data === "object" && res.data && "detail" in (res.data as Record<string, unknown>)
        ? String((res.data as Record<string, unknown>).detail)
        : typeof res.data === "string"
          ? res.data
          : `HTTP ${res.status}`;
    throw new Error(`Taskforce discover API error ${res.status}: ${detail}`);
  }
  return res.data as T;
}

export async function callTaskforceDiscover(
  args: TaskforceDiscoverArgs,
  fetchArgs: { bearerToken?: string } = {},
): Promise<TaskforceDiscoverResponse> {
  const { demo, ...body } = args;
  const res = await enderaiFetch({
    method: "POST",
    path: "/api/v1/v2/taskforce/discover",
    query: demo ? { demo: true } : undefined,
    bearerToken: fetchArgs.bearerToken,
    json: body,
  });
  return asJson<TaskforceDiscoverResponse>(res);
}
