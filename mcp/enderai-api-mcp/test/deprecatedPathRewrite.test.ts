import { describe, expect, it } from "vitest";

import { rewriteDeprecatedApiPath } from "../src/deprecatedPathRewrite.js";

describe("rewriteDeprecatedApiPath", () => {
  it("rewrites /api/v1/me to /api/v1/users/me", () => {
    const res = rewriteDeprecatedApiPath("/api/v1/me");
    expect(res.path).toBe("/api/v1/users/me");
    expect(res.rewrites.length).toBeGreaterThan(0);
  });

  it("rewrites library to artifacts (preserving tail)", () => {
    expect(rewriteDeprecatedApiPath("/api/v1/library/").path).toBe("/api/v1/artifacts/");
    expect(rewriteDeprecatedApiPath("/api/v1/library/abc").path).toBe(
      "/api/v1/artifacts/abc",
    );
    expect(rewriteDeprecatedApiPath("/api/v1/library/workflow-keys").path).toBe(
      "/api/v1/artifacts/workflow-keys",
    );
  });

  it("rewrites tasks to threads", () => {
    expect(rewriteDeprecatedApiPath("/api/v1/tasks/").path).toBe("/api/v1/threads/");
    expect(rewriteDeprecatedApiPath("/api/v1/tasks/123").path).toBe("/api/v1/threads/123");
  });

  it("rewrites task runs to thread executions", () => {
    expect(rewriteDeprecatedApiPath("/api/v1/tasks/123/runs").path).toBe(
      "/api/v1/threads/123/executions",
    );
    expect(rewriteDeprecatedApiPath("/api/v1/tasks/123/runs/456").path).toBe(
      "/api/v1/threads/123/executions/456",
    );
  });

  it("rewrites runs to executions", () => {
    expect(rewriteDeprecatedApiPath("/api/v1/runs/start").path).toBe(
      "/api/v1/executions/start",
    );
    expect(rewriteDeprecatedApiPath("/api/v1/runs/abc/events").path).toBe(
      "/api/v1/executions/abc/events",
    );
  });

  it("does not rewrite unrelated paths", () => {
    const res = rewriteDeprecatedApiPath("/api/v1/utils/health-check/");
    expect(res.path).toBe("/api/v1/utils/health-check/");
    expect(res.rewrites).toEqual([]);
  });
});

