import { enderaiFetch, type ResponseSummary } from "../http.js";
import type {
  V2Document,
  V2DocumentsList,
  V2DocumentUpdate,
} from "./types.js";

type ClientArgs = {
  bearerToken?: string;
  demo?: boolean;
};

function demoQuery(demo: boolean | undefined): Record<string, unknown> | undefined {
  return demo ? { demo: true } : undefined;
}

function asJson<T>(res: ResponseSummary): T {
  if (!res.ok) {
    const detail =
      typeof res.data === "object" && res.data && "detail" in (res.data as Record<string, unknown>)
        ? String((res.data as Record<string, unknown>).detail)
        : typeof res.data === "string"
          ? res.data
          : `HTTP ${res.status}`;
    throw new Error(`V2 document API error ${res.status}: ${detail}`);
  }
  return res.data as T;
}

export async function listV2Documents(args: ClientArgs = {}): Promise<V2DocumentsList> {
  const res = await enderaiFetch({
    method: "GET",
    path: "/api/v1/v2/documents/",
    query: demoQuery(args.demo),
    bearerToken: args.bearerToken,
  });
  return asJson<V2DocumentsList>(res);
}

export async function readV2Document(
  documentId: string,
  args: ClientArgs = {},
): Promise<V2Document> {
  const res = await enderaiFetch({
    method: "GET",
    path: `/api/v1/v2/documents/${documentId}`,
    query: demoQuery(args.demo),
    bearerToken: args.bearerToken,
  });
  return asJson<V2Document>(res);
}

export type V2DocumentCreate = {
  title: string;
  description?: string;
  human_summary?: string;
  ai_generated_summary?: string;
  collaborators?: string[];
  main_body?: V2Document["main_body"];
  details_file_name?: string;
  details_markdown_sections?: V2Document["details_markdown_sections"];
  visibility?: "private" | "organization";
};

export async function createV2Document(
  body: V2DocumentCreate,
  args: ClientArgs = {},
): Promise<V2Document> {
  const res = await enderaiFetch({
    method: "POST",
    path: "/api/v1/v2/documents/",
    query: demoQuery(args.demo),
    bearerToken: args.bearerToken,
    json: body,
  });
  return asJson<V2Document>(res);
}

export async function patchV2Document(
  documentId: string,
  body: V2DocumentUpdate,
  args: ClientArgs = {},
): Promise<V2Document> {
  const res = await enderaiFetch({
    method: "PATCH",
    path: `/api/v1/v2/documents/${documentId}`,
    query: demoQuery(args.demo),
    bearerToken: args.bearerToken,
    json: body,
  });
  return asJson<V2Document>(res);
}

export type TaskforceUsage = {
  model_id: string;
  input_tokens?: number;
  output_tokens?: number;
  cache_read_input_tokens?: number;
  cache_creation_input_tokens?: number;
  view_consulted?: "summary" | "details" | "both";
  occurred_at?: string;
};

export type MetricsEventPublic = {
  id: string;
  kind: string;
  occurred_at: string;
  model_id?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cache_read_tokens?: number | null;
  usd_amount?: string | null;
};

export type MetricsUsageRecorded = {
  events: MetricsEventPublic[];
};

export async function postV2DocumentUsage(
  documentId: string,
  usage: TaskforceUsage,
  args: ClientArgs = {},
): Promise<MetricsUsageRecorded> {
  const res = await enderaiFetch({
    method: "POST",
    path: `/api/v1/v2/documents/${documentId}/usage`,
    query: demoQuery(args.demo),
    bearerToken: args.bearerToken,
    json: usage,
  });
  return asJson<MetricsUsageRecorded>(res);
}

export type V2DocumentReusePayload = {
  score?: number | null;
  band?: "high" | "medium" | "low" | "explicit" | "forced-new" | null;
  reasons?: string[];
  usage?: TaskforceUsage;
};

export async function postV2DocumentReused(
  documentId: string,
  payload: V2DocumentReusePayload,
  args: ClientArgs = {},
): Promise<MetricsUsageRecorded> {
  const res = await enderaiFetch({
    method: "POST",
    path: `/api/v1/v2/documents/${documentId}/reused`,
    query: demoQuery(args.demo),
    bearerToken: args.bearerToken,
    json: payload,
  });
  return asJson<MetricsUsageRecorded>(res);
}
