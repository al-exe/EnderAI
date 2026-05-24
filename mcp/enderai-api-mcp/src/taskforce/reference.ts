/**
 * Thin client for POST /v2/taskforce/reference (TF-186).
 *
 * The `/tf` skill can call the backend directly, but this mirror keeps the
 * MCP package's Taskforce HTTP client surface complete.
 */

import { enderaiFetch, type ResponseSummary } from "../http.js";

export type TaskforceReferenceArgs = {
  session_id: string;
  document_ids: string[];
  user_prompt: string;
  occurred_at?: string;
  demo?: boolean;
};

export type TaskforceReferenceResponse = {
  updated_document_ids: string[];
  skipped_document_ids: string[];
};

function asJson<T>(res: ResponseSummary): T {
  if (!res.ok) {
    const detail =
      typeof res.data === "object" && res.data && "detail" in (res.data as Record<string, unknown>)
        ? String((res.data as Record<string, unknown>).detail)
        : typeof res.data === "string"
          ? res.data
          : `HTTP ${res.status}`;
    throw new Error(`Taskforce reference API error ${res.status}: ${detail}`);
  }
  return res.data as T;
}

export async function callTaskforceReference(
  args: TaskforceReferenceArgs,
  fetchArgs: { bearerToken?: string } = {},
): Promise<TaskforceReferenceResponse> {
  const { demo, ...body } = args;
  const res = await enderaiFetch({
    method: "POST",
    path: "/api/v1/v2/taskforce/reference",
    query: demo ? { demo: true } : undefined,
    bearerToken: fetchArgs.bearerToken,
    json: body,
  });
  return asJson<TaskforceReferenceResponse>(res);
}
