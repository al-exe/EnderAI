export const REQUIRED_HOOK_TOOLS = [
  "enderai_begin_document",
  "enderai_finish_document",
  "enderai_health_check",
  "enderai_openapi",
  "enderai_request",
  "enderai_session_info",
  "enderai_update_document",
];

export const REQUIRED_HOOK_ROUTE_PATHS = [
  "/api/v1/utils/health-check/",
  "/api/v1/v2/documents/",
  "/api/v1/v2/documents/{document_id}",
];

export function summarizeToolText(content: unknown): string {
  if (!Array.isArray(content) || content.length === 0) return String(content);
  const first: any = content[0];
  const text = typeof first?.text === "string" ? first.text : JSON.stringify(first);
  const oneLine = text.replace(/\s+/g, " ").trim();
  return oneLine.length > 220 ? `${oneLine.slice(0, 220)}...` : oneLine;
}

export function parseToolTextJson<T>(content: unknown): T {
  if (!Array.isArray(content) || content.length === 0) {
    throw new Error(`Expected MCP text content, received: ${String(content)}`);
  }
  const first: any = content[0];
  if (typeof first?.text !== "string") {
    throw new Error(`Expected MCP text item, received: ${JSON.stringify(first)}`);
  }
  return JSON.parse(first.text) as T;
}

export function assertRequiredToolNames(toolNames: string[]): void {
  const missing = REQUIRED_HOOK_TOOLS.filter((toolName) => !toolNames.includes(toolName));
  if (missing.length > 0) {
    throw new Error(`Missing required MCP hook tools: ${missing.join(", ")}`);
  }
}

export function assertRequiredHookRoutes(openapiPayload: any): void {
  const paths = Object.keys(openapiPayload?.data?.paths ?? {});
  const missing = REQUIRED_HOOK_ROUTE_PATHS.filter((path) => !paths.includes(path));
  if (missing.length > 0) {
    throw new Error(`Missing required backend hook routes: ${missing.join(", ")}`);
  }
}
