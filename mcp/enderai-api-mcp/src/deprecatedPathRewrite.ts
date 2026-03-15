export type PathRewrite = {
  from: string;
  to: string;
  reason: string;
};

export type RewriteResult = {
  path: string;
  rewrites: PathRewrite[];
};

// Backward-compat for older clients / prompts that still reference pre-migration endpoints.
//
// We keep this intentionally narrow and explicit to avoid surprising rewrites of unrelated paths.
export function rewriteDeprecatedApiPath(path: string): RewriteResult {
  let out = path;
  const rewrites: PathRewrite[] = [];

  function apply(re: RegExp, replacement: string, reason: string): void {
    if (!re.test(out)) return;
    const prev = out;
    out = out.replace(re, replacement);
    if (out !== prev) rewrites.push({ from: prev, to: out, reason });
  }

  // `/api/v1/me` -> `/api/v1/users/me`
  apply(/^\/api\/v1\/me\/?$/, "/api/v1/users/me", "me->users/me");

  // `/api/v1/library/*` -> `/api/v1/artifacts/*`
  apply(/^\/api\/v1\/library(\/|$)/, "/api/v1/artifacts$1", "library->artifacts");

  // `/api/v1/tasks/*` -> `/api/v1/threads/*`
  apply(/^\/api\/v1\/tasks(\/|$)/, "/api/v1/threads$1", "tasks->threads");

  // `/api/v1/threads/{id}/runs/*` -> `/api/v1/threads/{id}/executions/*`
  // This targets older "task runs" URLs after the tasks->threads rewrite.
  apply(
    /^\/api\/v1\/threads\/([^/]+)\/runs(\/|$)/,
    "/api/v1/threads/$1/executions$2",
    "thread runs->executions",
  );

  // `/api/v1/runs/*` -> `/api/v1/executions/*`
  apply(/^\/api\/v1\/runs(\/|$)/, "/api/v1/executions$1", "runs->executions");

  return { path: out, rewrites };
}

