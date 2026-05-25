import http from "node:http";
import { randomUUID, webcrypto } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMcpServer } from "../src/mcpServer.js";

if (!(globalThis as any).crypto) {
  (globalThis as any).crypto = webcrypto;
}

const realFetch = globalThis.fetch.bind(globalThis);
const mockFetch = vi.fn();
(globalThis as any).fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url;
  if (url.startsWith("http://127.0.0.1")) {
    return await realFetch(input as any, init);
  }
  return await mockFetch(input, init);
});

type Session = {
  id: string;
  transport: WebStandardStreamableHTTPServerTransport;
  server: ReturnType<typeof createMcpServer>;
};

type Harness = {
  client: Client;
  close: () => Promise<void>;
};

let skillsDir: string | undefined;

beforeEach(() => {
  mockFetch.mockReset();
  process.env.ENDERAI_BASE_URL = "https://enderai-backend.onrender.com";
  delete process.env.ENDERAI_BEARER_TOKEN;
  skillsDir = mkdtempSync(path.join(os.tmpdir(), "enderai-skills-test-"));
  process.env.ENDERAI_SKILLS_DIR = skillsDir;
});

afterEach(() => {
  if (skillsDir) rmSync(skillsDir, { recursive: true, force: true });
  skillsDir = undefined;
  delete process.env.ENDERAI_SKILLS_DIR;
  delete process.env.ENDERAI_BEARER_TOKEN;
});

describe("guided case workflow MCP tools", () => {
  it("lists the high-level case workflow tools", async () => {
    const harness = await createHarness();
    try {
      const tools = await harness.client.listTools();
      const names = tools.tools.map((tool) => tool.name);
      expect(names).toEqual(
        expect.arrayContaining([
          "enderai_begin_case",
          "enderai_update_case",
          "enderai_use_skill",
          "enderai_finish_case",
          "enderai_begin_document",
          "enderai_update_document",
          "enderai_finish_document",
          "enderai_request",
          "enderai_session_info",
          "enderai_openapi",
          "enderai_health_check",
        ]),
      );
    } finally {
      await harness.close();
    }
  });

  it("enforces the begin → update → finish workflow", async () => {
    const harness = await createHarness();
    try {
      const beforeBegin = await harness.client.callTool({
        name: "enderai_update_case",
        arguments: { summary_current: "Should fail before begin" },
      });
      expect(summarizeToolText(beforeBegin.content)).toContain(
        "Run enderai_begin_case first or provide case_id",
      );

      const topicId = "11111111-1111-1111-1111-111111111111";
      const caseId = "22222222-2222-2222-2222-222222222222";
      const skillId = "33333333-3333-3333-3333-333333333333";

      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            data: [],
            count: 0,
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            policy: { confidence: "low", max_topics: 1 },
            candidates: [],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: topicId,
            title: "Core model",
            workflow_key: "core_model",
            status: "open",
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            policy: { confidence: "high", max_topics: 1 },
            matched_topics: [],
            selected_topic_ids: [topicId],
            selected_case_ids: [caseId],
            relevant_cases: [
              {
                case_id: caseId,
                title: "Hydration gap",
                short_summary: "Hydration gap",
                outcome: null,
                key_files: [
                  "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
                ],
                key_symbols: [],
                key_errors: [],
                key_commands: [],
                why_selected: "request-text overlap: hydration",
              },
            ],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
              matched_signals: ["hydration gap"],
              representative_cases: [caseId],
              recent_cases: [caseId],
              relevant_cases: [
                {
                  case_id: caseId,
                  title: "Hydration gap",
                  short_summary: "Hydration gap",
                  outcome: null,
                  key_files: [
                    "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
                  ],
                  key_symbols: [],
                  key_errors: [],
                  key_commands: [],
                  why_selected: "request-text overlap: hydration",
                },
              ],
              canonical_files: [
                "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
              ],
              canonical_symbols: [],
              canonical_errors: [],
              canonical_symptoms: [],
              pinned_takeaways: [],
              ambiguities: [],
              questions: [],
              negative_history: [],
              builder_version: "v1",
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            title: "Hydration gap",
            status: "running",
            input_summary: "Hydration gap",
            summary_current: "Hydration gap",
            files: [
              "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
            ],
            symbols: [],
            errors: [],
            symptoms: [],
            commands: [],
            hypotheses: [],
            changes: [],
            next_steps: [],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
            },
          }),
        )
        .mockResolvedValueOnce(
          selectedSkillUseResponse({
            skillId,
            topicId,
            caseId,
            title: "Core Model Workflow Skill",
            slug: "core-model-workflow-skill",
            instructionsMd: "# Skill: Core Model\n\nUse this hydration checklist.",
            matchedSignals: ["hydration gap"],
            files: [
              "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
            ],
          }),
        );

      const begin = await harness.client.callTool({
        name: "enderai_begin_case",
        arguments: {
          topic_title: "Core model",
          workflow_key: "core_model",
          request_summary: "Hydration gap",
          case_title: "Hydration gap",
          files: [
            "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
          ],
        },
      });
      const beginBody = JSON.parse(summarizeToolText(begin.content));
      expect(beginBody.next.case_id).toBe(caseId);
      expect(beginBody.context_pack.context_pack_snapshot.topic_id).toBe(topicId);
      expect(beginBody.hydration.hydration_status).toBe("attached");
      expect(beginBody.hydration.context_pack_attached).toBe(true);
      expect(beginBody.hydration.relevant_case_count).toBe(1);
      expect(beginBody.skill_hydration.status).toBe("synced");
      expect(beginBody.hydration.skill_hydration_status).toBe("synced");
      expect(beginBody.hydration.local_skill_file_count).toBe(1);
      const syncedSkill = beginBody.skill_hydration.local_skill_sync.local_skill_files[0];
      expect(syncedSkill.path).toContain(skillsDir);
      const syncedSkillText = readFileSync(syncedSkill.path, "utf8");
      expect(syncedSkillText).toContain("# EnderAI Skill: Core Model Workflow Skill");
      expect(syncedSkillText).toContain("# Skill: Core Model");
      expect(mockFetch.mock.calls[0][0].toString()).toContain("/api/v1/topics/");
      expect(mockFetch.mock.calls[1][0].toString()).toContain("/api/v1/topics/match");
      expect(JSON.parse(mockFetch.mock.calls[1][1].body)).toMatchObject({
        title: "Hydration gap",
        request_summary: "Hydration gap",
        files: [
          "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
        ],
        limit: 3,
      });
      expect(mockFetch.mock.calls[2][0].toString()).toContain("/api/v1/topics/");
      expect(mockFetch.mock.calls[3][0].toString()).toContain("/api/v1/context-packs/build");
      expect(mockFetch.mock.calls[4][0].toString()).toContain("/api/v1/cases/");
      expect(mockFetch.mock.calls[5][0].toString()).toContain("/api/v1/skills/use");
      expect(JSON.parse(mockFetch.mock.calls[3][1].body)).toMatchObject({
        topic_id: topicId,
        request_summary: "Hydration gap",
      });
      expect(JSON.parse(mockFetch.mock.calls[5][1].body)).toMatchObject({
        case_id: caseId,
        request_summary: "Hydration gap",
        files: [
          "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
        ],
      });

      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            title: "Hydration gap",
            status: "running",
            input_summary: "Hydration gap",
            summary_current: "Hydration gap",
            files: [
              "demo/full-stack-fastapi-template/backend/app/api/routes/cases.py",
            ],
            symbols: [],
            errors: [],
            symptoms: [],
            commands: [],
            hypotheses: [],
            changes: [],
            next_steps: [],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            title: "Hydration gap",
            status: "running",
            input_summary: "Hydration gap",
            summary_current: "Captured first evidence",
            files: ["backend/app/api/routes/cases.py"],
            symbols: [],
            errors: ["missing command history"],
            symptoms: [],
            commands: [],
            hypotheses: [],
            changes: [],
            next_steps: [],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: 1,
            execution_id: caseId,
            type: "mcp_progress",
            message: "Captured first evidence",
          }),
        );

      const update = await harness.client.callTool({
        name: "enderai_update_case",
        arguments: {
          summary_current: "Captured first evidence",
          files: ["backend/app/api/routes/cases.py"],
          errors: ["missing command history"],
          progress_note: "Captured first evidence",
        },
      });
      const updateBody = JSON.parse(summarizeToolText(update.content));
      expect(updateBody.case.summary_current).toBe("Captured first evidence");
      expect(updateBody.progress_event.message).toBe("Captured first evidence");
      expect(mockFetch.mock.calls[6][0].toString()).toContain(`/api/v1/cases/${caseId}`);
      expect(mockFetch.mock.calls[7][0].toString()).toContain(`/api/v1/cases/${caseId}`);
      expect(mockFetch.mock.calls[8][0].toString()).toContain(
        `/api/v1/cases/${caseId}/events`,
      );

      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            title: "Hydration gap",
            status: "running",
            input_summary: "Hydration gap",
            summary_current: "Captured first evidence",
            files: ["backend/app/api/routes/cases.py"],
            symbols: [],
            errors: ["missing command history"],
            symptoms: [],
            commands: [],
            hypotheses: [],
            changes: [],
            next_steps: [],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            title: "Hydration gap",
            status: "done",
            input_summary: "Hydration gap",
            summary_current: "Captured first evidence",
            files: ["backend/app/api/routes/cases.py"],
            symbols: [],
            errors: ["missing command history"],
            symptoms: [],
            commands: [],
            hypotheses: [],
            changes: [],
            outcome: "Hydration now carries the right prior context.",
            next_steps: [],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: 2,
            execution_id: caseId,
            type: "mcp_finish",
            message: "Closed the case",
          }),
        );

      const finish = await harness.client.callTool({
        name: "enderai_finish_case",
        arguments: {
          outcome: "Hydration now carries the right prior context.",
          closing_note: "Closed the case",
        },
      });
      const finishBody = JSON.parse(summarizeToolText(finish.content));
      expect(finishBody.case.status).toBe("done");
      expect(finishBody.session_context_cleared).toBe(true);
      expect(finishBody.closing_event.message).toBe("Closed the case");

      const afterFinish = await harness.client.callTool({
        name: "enderai_update_case",
        arguments: { summary_current: "Should fail after finish" },
      });
      expect(summarizeToolText(afterFinish.content)).toContain(
        "Run enderai_begin_case first or provide case_id",
      );
    } finally {
      await harness.close();
    }
  });

  it("clears the active case context when finish_case fails after the case is closed", async () => {
    const harness = await createHarness();
    try {
      const topicId = "11111111-1111-1111-1111-111111111111";
      const caseId = "22222222-2222-2222-2222-222222222222";

      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            data: [],
            count: 0,
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            policy: { confidence: "low", max_topics: 1 },
            candidates: [],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: topicId,
            title: "Core model",
            workflow_key: "core_model",
            status: "open",
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            policy: { confidence: "high", max_topics: 1 },
            matched_topics: [],
            selected_topic_ids: [topicId],
            selected_case_ids: [],
            relevant_cases: [],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
              matched_signals: [],
              representative_cases: [],
              recent_cases: [],
              relevant_cases: [],
              canonical_files: [],
              canonical_symbols: [],
              canonical_errors: [],
              canonical_symptoms: [],
              pinned_takeaways: [],
              ambiguities: [],
              questions: [],
              negative_history: [],
              builder_version: "v1",
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            status: "running",
            summary_current: "Hydration gap",
          }),
        )
        .mockResolvedValueOnce(
          noSkillUseResponse(),
        );

      await harness.client.callTool({
        name: "enderai_begin_case",
        arguments: {
          topic_title: "Core model",
          workflow_key: "core_model",
          request_summary: "Hydration gap",
        },
      });

      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            status: "running",
            summary_current: "Hydration gap",
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            status: "done",
            closed_at: "2026-03-22T22:47:16.572001Z",
            outcome: "Closed",
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse(
            {
              detail: "event append failed",
            },
            500,
          ),
        );

      const finish = await harness.client.callTool({
        name: "enderai_finish_case",
        arguments: {
          closing_note: "Closed the case",
        },
      });
      expect(summarizeToolText(finish.content)).toContain(
        "enderai_finish_case failed to append the closing event",
      );

      const info = await harness.client.callTool({
        name: "enderai_session_info",
        arguments: {},
      });
      const infoBody = JSON.parse(summarizeToolText(info.content));
      expect(infoBody.active_case_id).toBeNull();
      expect(infoBody.active_topic_id).toBeNull();
    } finally {
      await harness.close();
    }
  });

  it("uses a generated skill for the active case", async () => {
    const harness = await createHarness();
    try {
      const topicId = "11111111-1111-1111-1111-111111111111";
      const caseId = "22222222-2222-2222-2222-222222222222";
      const skillId = "33333333-3333-3333-3333-333333333333";

      mockFetch
        .mockResolvedValueOnce(jsonResponse({ data: [], count: 0 }))
        .mockResolvedValueOnce(
          jsonResponse({
            policy: { confidence: "low", max_topics: 1 },
            candidates: [],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: topicId,
            title: "Hosted MCP OAuth Rotation",
            workflow_key: "hosted_mcp_oauth_rotation",
            status: "open",
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            policy: { confidence: "high", max_topics: 1 },
            matched_topics: [],
            selected_topic_ids: [topicId],
            selected_case_ids: [],
            relevant_cases: [],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
              topic_summary: "Hosted MCP refresh-token rotation fixes.",
              matched_signals: ["invalid_grant"],
              representative_cases: [],
              recent_cases: [],
              relevant_cases: [],
              canonical_files: ["mcp/enderai-api-mcp/src/sessionAuth.ts"],
              canonical_symbols: ["refreshHostedSession"],
              canonical_errors: ["invalid_grant"],
              canonical_symptoms: ["hosted agents failed after key rollover"],
              pinned_takeaways: ["Clear cached credentials on invalid_grant."],
              ambiguities: [],
              questions: [],
              negative_history: [],
              builder_version: "v1",
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            title: "OAuth rollover failure",
            status: "running",
            input_summary: "Hosted MCP returns invalid_grant after key rollover.",
            summary_current: "Hosted MCP returns invalid_grant after key rollover.",
            files: ["mcp/enderai-api-mcp/src/sessionAuth.ts"],
            symbols: ["refreshHostedSession"],
            errors: ["invalid_grant"],
            symptoms: ["hosted agents failed after key rollover"],
            commands: [],
            hypotheses: [],
            changes: [],
            next_steps: [],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
              topic_summary: "Hosted MCP refresh-token rotation fixes.",
              pinned_takeaways: ["Clear cached credentials on invalid_grant."],
              questions: [],
            },
          }),
        )
        .mockResolvedValueOnce(noSkillUseResponse())
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            title: "OAuth rollover failure",
            status: "running",
            input_summary: "Hosted MCP returns invalid_grant after key rollover.",
            summary_current: "Hosted MCP returns invalid_grant after key rollover.",
            files: ["mcp/enderai-api-mcp/src/sessionAuth.ts"],
            symbols: ["refreshHostedSession"],
            errors: ["invalid_grant"],
            symptoms: ["hosted agents failed after key rollover"],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "high",
              topic_summary: "Hosted MCP refresh-token rotation fixes.",
              pinned_takeaways: ["Clear cached credentials on invalid_grant."],
              questions: [],
            },
          }),
        )
        .mockResolvedValueOnce(
          selectedSkillUseResponse({
            skillId,
            topicId,
            caseId,
            title: "Hosted MCP OAuth Rotation Workflow Skill",
            slug: "hosted-mcp-oauth-rotation-workflow-skill",
            instructionsMd: "# Skill: Hosted MCP OAuth Rotation",
            matchedSignals: ["invalid_grant"],
            files: ["mcp/enderai-api-mcp/src/sessionAuth.ts"],
            symbols: ["refreshHostedSession"],
            errors: ["invalid_grant"],
          }),
        );

      await harness.client.callTool({
        name: "enderai_begin_case",
        arguments: {
          topic_title: "Hosted MCP OAuth Rotation",
          workflow_key: "hosted_mcp_oauth_rotation",
          request_summary: "Hosted MCP returns invalid_grant after key rollover.",
          files: ["mcp/enderai-api-mcp/src/sessionAuth.ts"],
          errors: ["invalid_grant"],
        },
      });

      const useSkill = await harness.client.callTool({
        name: "enderai_use_skill",
        arguments: {},
      });
      const useSkillBody = JSON.parse((useSkill.content as any)[0].text);

      expect(useSkillBody.skill_use.selected_skill.id).toBe(skillId);
      expect(useSkillBody.local_skill_sync.local_skill_files).toHaveLength(1);
      const localSkillFile = useSkillBody.local_skill_sync.local_skill_files[0].path;
      expect(readFileSync(localSkillFile, "utf8")).toContain(
        "# Skill: Hosted MCP OAuth Rotation",
      );
      expect(useSkillBody.next.case_id).toBe(caseId);
      expect(useSkillBody.next.local_skills_dir).toBe(skillsDir);
      expect(mockFetch.mock.calls[5][0].toString()).toContain("/api/v1/skills/use");
      expect(mockFetch.mock.calls[6][0].toString()).toContain(`/api/v1/cases/${caseId}`);
      expect(mockFetch.mock.calls[7][0].toString()).toContain("/api/v1/skills/use");
      expect(JSON.parse(mockFetch.mock.calls[7][1].body)).toMatchObject({
        case_id: caseId,
        request_summary: "Hosted MCP returns invalid_grant after key rollover.",
        files: ["mcp/enderai-api-mcp/src/sessionAuth.ts"],
        errors: ["invalid_grant"],
      });
    } finally {
      await harness.close();
    }
  });

  it("reuses a matched topic when begin_case only has request signals", async () => {
    const harness = await createHarness();
    try {
      const topicId = "33333333-3333-3333-3333-333333333333";
      const caseId = "44444444-4444-4444-4444-444444444444";

      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            data: [],
            count: 0,
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            policy: { confidence: "medium", max_topics: 1 },
            candidates: [
              {
                topic: {
                  id: topicId,
                  title: "Frontend table layout",
                  workflow_key: "frontend_table_layout",
                  status: "open",
                  last_used_at: "2026-05-02T06:30:00.000Z",
                },
                score: 5.8,
                confidence: "medium",
                matched_signals: ["frontend table layout"],
                reasoning: ["context similarity: 0.84"],
              },
            ],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            policy: { confidence: "medium", max_topics: 1 },
            matched_topics: [],
            selected_topic_ids: [topicId],
            selected_case_ids: [caseId],
            relevant_cases: [],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "medium",
              matched_signals: ["frontend table layout"],
              representative_cases: [],
              recent_cases: [],
              relevant_cases: [],
              canonical_files: ["src/components/Common/SplitDataTable.tsx"],
              canonical_symbols: [],
              canonical_errors: [],
              canonical_symptoms: [],
              pinned_takeaways: [],
              ambiguities: [],
              questions: [],
              negative_history: [],
              builder_version: "v1",
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: caseId,
            topic_id: topicId,
            title: "Fix split table overflow clipping",
            status: "running",
            input_summary: "Fix split table overflow clipping",
            summary_current: "Fix split table overflow clipping",
            files: ["src/components/Common/SplitScrollableTable.tsx"],
            symbols: [],
            errors: [],
            symptoms: [],
            commands: [],
            hypotheses: [],
            changes: [],
            next_steps: [],
            context_pack_snapshot: {
              topic_id: topicId,
              confidence: "medium",
            },
          }),
        )
        .mockResolvedValueOnce(noSkillUseResponse());

      const begin = await harness.client.callTool({
        name: "enderai_begin_case",
        arguments: {
          request_summary: "Fix split table overflow clipping",
          files: ["src/components/Common/SplitScrollableTable.tsx"],
          contexts: ["frontend table layout", "topics cases table header alignment"],
        },
      });
      const beginBody = JSON.parse(summarizeToolText(begin.content));
      expect(beginBody.topic.id).toBe(topicId);
      expect(beginBody.reused_topic).toBe(true);
      expect(mockFetch.mock.calls[0][0].toString()).toContain("/api/v1/topics/");
      expect(mockFetch.mock.calls[1][0].toString()).toContain("/api/v1/topics/match");
      expect(JSON.parse(mockFetch.mock.calls[1][1].body)).toMatchObject({
        title: "Fix split table overflow clipping",
        request_summary: "Fix split table overflow clipping",
        files: ["src/components/Common/SplitScrollableTable.tsx"],
        contexts: ["frontend table layout", "topics cases table header alignment"],
        limit: 3,
      });
      expect(JSON.parse(mockFetch.mock.calls[3][1].body)).toMatchObject({
        topic_id: topicId,
      });
      expect(mockFetch.mock.calls[4][0].toString()).toContain("/api/v1/skills/use");
    } finally {
      await harness.close();
    }
  });

  it("allows begin_case to recover from a stale closed active case", async () => {
    const harness = await createHarness();
    try {
      const closedTopicId = "11111111-1111-1111-1111-111111111111";
      const closedCaseId = "22222222-2222-2222-2222-222222222222";
      const nextTopicId = "33333333-3333-3333-3333-333333333333";
      const nextCaseId = "44444444-4444-4444-4444-444444444444";

      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          id: closedCaseId,
          topic_id: closedTopicId,
          status: "done",
          closed_at: "2026-03-22T22:47:16.572001Z",
          summary_current: "Already closed",
        }),
      );

      await harness.client.callTool({
        name: "enderai_update_case",
        arguments: {
          case_id: closedCaseId,
          summary_current: "Already closed",
        },
      });

      mockFetch
        .mockResolvedValueOnce(
          jsonResponse({
            id: closedCaseId,
            topic_id: closedTopicId,
            status: "done",
            closed_at: "2026-03-22T22:47:16.572001Z",
            summary_current: "Already closed",
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            data: [],
            count: 0,
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            policy: { confidence: "low", max_topics: 1 },
            candidates: [],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: nextTopicId,
            title: "Recovered topic",
            workflow_key: "recovered_topic",
            status: "open",
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            policy: { confidence: "high", max_topics: 1 },
            matched_topics: [],
            selected_topic_ids: [nextTopicId],
            selected_case_ids: [],
            relevant_cases: [],
            context_pack_snapshot: {
              topic_id: nextTopicId,
              confidence: "high",
              matched_signals: [],
              representative_cases: [],
              recent_cases: [],
              relevant_cases: [],
              canonical_files: [],
              canonical_symbols: [],
              canonical_errors: [],
              canonical_symptoms: [],
              pinned_takeaways: [],
              ambiguities: [],
              questions: [],
              negative_history: [],
              builder_version: "v1",
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: nextCaseId,
            topic_id: nextTopicId,
            status: "running",
            summary_current: "Recovered begin case",
          }),
        )
        .mockResolvedValueOnce(noSkillUseResponse());

      const begin = await harness.client.callTool({
        name: "enderai_begin_case",
        arguments: {
          topic_title: "Recovered topic",
          workflow_key: "recovered_topic",
          request_summary: "Recovered begin case",
        },
      });
      const beginBody = JSON.parse(summarizeToolText(begin.content));
      expect(beginBody.next.case_id).toBe(nextCaseId);
      expect(beginBody.case.topic_id).toBe(nextTopicId);
    } finally {
      await harness.close();
    }
  });

  it("blocks write-like enderai_request calls before a case begins", async () => {
    const harness = await createHarness();
    try {
      const beforeBegin = await harness.client.callTool({
        name: "enderai_request",
        arguments: {
          method: "POST",
          path: "/api/v1/artifacts/",
          json: { title: "Should fail" },
        },
      });

      expect(summarizeToolText(beforeBegin.content)).toContain(
        "enderai_request write-like calls require an active case",
      );
      expect(mockFetch).not.toHaveBeenCalled();
    } finally {
      await harness.close();
    }
  });

  it("does not let audit.execution_id bypass the active-case guard", async () => {
    const harness = await createHarness();
    try {
      const beforeBegin = await harness.client.callTool({
        name: "enderai_request",
        arguments: {
          method: "POST",
          path: "/api/v1/artifacts/",
          json: { title: "Should still fail" },
          audit: {
            execution_id: "22222222-2222-2222-2222-222222222222",
          },
        },
      });

      expect(summarizeToolText(beforeBegin.content)).toContain(
        "audit.execution_id does not replace an active case",
      );
      expect(mockFetch).not.toHaveBeenCalled();
    } finally {
      await harness.close();
    }
  });

  it("normalizes stringified JSON bodies for write requests", async () => {
    const harness = await createHarness();
    try {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          id: "22222222-2222-2222-2222-222222222222",
          status: "done",
        }),
      );

      const result = await harness.client.callTool({
        name: "enderai_request",
        arguments: {
          method: "PATCH",
          path: "/api/v1/cases/22222222-2222-2222-2222-222222222222",
          json: "{\"status\":\"done\"}",
          unsafe_write_reason: "Regression test for stringified JSON transport",
        },
      });
      const resultBody = JSON.parse(summarizeToolText(result.content));

      expect(resultBody.status).toBe(200);
      expect(mockFetch.mock.calls[0][0].toString()).toContain(
        "/api/v1/cases/22222222-2222-2222-2222-222222222222",
      );
      expect(JSON.parse(mockFetch.mock.calls[0][1]?.body as string)).toEqual({
        status: "done",
      });
    } finally {
      await harness.close();
    }
  });

  it("reports session readiness from ENDERAI_BEARER_TOKEN fallback", async () => {
    process.env.ENDERAI_BEARER_TOKEN = "operator-bearer-token";

    const harness = await createHarness();
    try {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          id: "user-1",
          email: "frontend-test@example.com",
          full_name: "Frontend Test User",
        }),
      );

      const info = await harness.client.callTool({
        name: "enderai_session_info",
        arguments: {},
      });
      const infoBody = JSON.parse(summarizeToolText(info.content));

      expect(infoBody.session_ready).toBe(true);
      expect(infoBody.user).toMatchObject({
        id: "user-1",
        email: "frontend-test@example.com",
        full_name: "Frontend Test User",
      });
      expect(infoBody.local_skills_dir).toBe(skillsDir);
      expect(infoBody.skills_discovery).toContain("local_skill_files");
      expect(mockFetch.mock.calls[0][0].toString()).toContain("/api/v1/users/me");
      expect(mockFetch.mock.calls[0][1]?.headers).toMatchObject({
        authorization: "Bearer operator-bearer-token",
      });
    } finally {
      await harness.close();
    }
  });
});

function noSkillUseResponse(): Response {
  return jsonResponse({
    selected_skill: null,
    matched_skills: [],
    instructions_md: null,
    confidence: "low",
    matched_signals: [],
    provenance: {},
    agent_usage_note:
      "No generated EnderAI skill matched this request. Continue with ContextPack hydration.",
  });
}

function selectedSkillUseResponse(params: {
  skillId: string;
  topicId: string;
  caseId: string;
  title: string;
  slug: string;
  instructionsMd: string;
  matchedSignals: string[];
  files?: string[];
  symbols?: string[];
  errors?: string[];
  symptoms?: string[];
}): Response {
  const skill = {
    id: params.skillId,
    title: params.title,
    slug: params.slug,
    description: `Reusable workflow generated from ${params.title}.`,
    status: "published",
    source_type: "topic",
    source_topic_id: params.topicId,
    source_case_ids: [params.caseId],
    owner_ids: ["test-owner"],
    is_demo: false,
    trigger_phrases: params.matchedSignals,
    files: params.files ?? [],
    symbols: params.symbols ?? [],
    errors: params.errors ?? [],
    symptoms: params.symptoms ?? [],
    instructions_md: params.instructionsMd,
    confidence: "high",
    source_snapshot: { topic: { id: params.topicId }, cases: [params.caseId] },
    usage_count: 0,
    created_at: "2026-05-04T00:00:00.000Z",
    updated_at: "2026-05-04T00:00:00.000Z",
    last_used_at: null,
  };
  return jsonResponse({
    selected_skill: skill,
    matched_skills: [
      {
        skill,
        score: 8.5,
        confidence: "high",
        matched_signals: params.matchedSignals,
        reasoning: ["request signals matched generated skill"],
      },
    ],
    instructions_md: params.instructionsMd,
    confidence: "high",
    matched_signals: params.matchedSignals,
    provenance: { topic: { id: params.topicId }, cases: [params.caseId] },
    agent_usage_note: "Use the returned skill after ContextPack hydration.",
  });
}

function v2DocumentResponse(params: {
  id: string;
  title: string;
  description?: string;
  aiGeneratedSummary?: string;
  detailsSections?: Array<{ anchor_id: string; markdown: string }>;
}) {
  const detailsSections = params.detailsSections ?? [];
  return {
    id: params.id,
    owner_id: "99999999-9999-9999-9999-999999999999",
    organization_id: null,
    visibility: "private",
    title: params.title,
    description: params.description ?? "Document description.",
    human_summary: "",
    ai_generated_summary: params.aiGeneratedSummary ?? "",
    collaborators: [],
    main_body:
      detailsSections.length > 0
        ? [
            {
              segments: [
                {
                  text: params.aiGeneratedSummary ?? params.description ?? params.title,
                  evidence_anchor_id: detailsSections[0].anchor_id,
                },
              ],
            },
          ]
        : [],
    details_file_name: "taskforce-mcp.details.md",
    details_markdown_sections: detailsSections,
    is_demo: false,
    created_at: "2026-05-18T00:00:00.000Z",
    updated_at: "2026-05-18T00:00:00.000Z",
  };
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function createHarness(): Promise<Harness> {
  const sessions = new Map<string, Session>();
  const httpServer = http.createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
    if (url.pathname !== "/mcp") {
      res.writeHead(404);
      res.end();
      return;
    }

    const method = (req.method ?? "GET").toUpperCase();
    const sessionId = headerString(req, "mcp-session-id");
    const parsedBody = method === "POST" ? await parseJsonBody(req, res) : undefined;
    if (method === "POST" && parsedBody === undefined) return;

    let session: Session | undefined;
    if (sessionId) {
      session = sessions.get(sessionId);
      if (!session && method === "POST" && containsInitialize(parsedBody)) {
        session = await createSession(sessions, sessionId);
      } else if (!session) {
        res.writeHead(404);
        res.end();
        return;
      }
    } else {
      if (!containsInitialize(parsedBody)) {
        res.writeHead(400);
        res.end("Bad Request: Server not initialized");
        return;
      }
      session = await createSession(sessions);
    }

    try {
      const webReq = nodeRequestToWebRequest(req, url);
      const webRes = await session.transport.handleRequest(webReq, { parsedBody });
      await sendWebResponse(res, webRes);
    } catch (err) {
      if (!res.headersSent) res.writeHead(500);
      res.end(err instanceof Error ? err.stack ?? err.message : String(err));
    }
  });

  await new Promise<void>((resolve) => httpServer.listen(0, "127.0.0.1", resolve));
  const addr = httpServer.address();
  if (!addr || typeof addr === "string") throw new Error("Unexpected address");

  const clientTransport = new StreamableHTTPClientTransport(
    new URL(`http://127.0.0.1:${addr.port}/mcp`),
  );
  const client = new Client({ name: "enderai-api-test", version: "0.0.0" });
  await client.connect(clientTransport);

  return {
    client,
    close: async () => {
      await client.close();
      await Promise.allSettled(
        [...sessions.values()].flatMap((session) => [
          session.transport.close(),
          session.server.close(),
        ]),
      );
      await new Promise<void>((resolve) => httpServer.close(() => resolve()));
    },
  };
}

async function createSession(
  sessions: Map<string, Session>,
  forcedId?: string,
): Promise<Session> {
  const id = forcedId ?? randomUUID();
  const transport = new WebStandardStreamableHTTPServerTransport({
    sessionIdGenerator: () => id,
    enableJsonResponse: true,
    onsessionclosed: async (closedId) => {
      const session = sessions.get(closedId);
      if (!session) return;
      sessions.delete(closedId);
      await Promise.allSettled([session.transport.close(), session.server.close()]);
    },
  });
  const server = createMcpServer();
  await server.connect(transport);
  const session = { id, transport, server };
  sessions.set(id, session);
  return session;
}

function headerString(req: http.IncomingMessage, name: string): string | undefined {
  const value = req.headers[name.toLowerCase()];
  if (!value) return undefined;
  return Array.isArray(value) ? value[0] : value;
}

async function parseJsonBody(
  req: http.IncomingMessage,
  res: http.ServerResponse,
): Promise<unknown | undefined> {
  const chunks: Uint8Array[] = [];
  for await (const chunk of req) {
    chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
  }
  const buf = Buffer.concat(chunks);
  if (buf.length === 0) {
    res.writeHead(400);
    res.end("Parse error: Invalid JSON");
    return undefined;
  }
  try {
    return JSON.parse(buf.toString("utf8"));
  } catch {
    res.writeHead(400);
    res.end("Parse error: Invalid JSON");
    return undefined;
  }
}

function containsInitialize(parsedBody: unknown): boolean {
  if (!parsedBody) return false;
  const messages = Array.isArray(parsedBody) ? parsedBody : [parsedBody];
  return messages.some(
    (message) =>
      message && typeof message === "object" && (message as any).method === "initialize",
  );
}

function nodeRequestToWebRequest(req: http.IncomingMessage, url: URL): Request {
  const headers = new Headers();
  for (const [key, value] of Object.entries(req.headers)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) {
      for (const item of value) headers.append(key, item);
    } else {
      headers.set(key, value);
    }
  }
  const method = (req.method ?? "GET").toUpperCase();
  return new Request(url.toString(), { method, headers });
}

async function sendWebResponse(res: http.ServerResponse, webRes: Response): Promise<void> {
  const headersObj: Record<string, string> = {};
  for (const [key, value] of webRes.headers.entries()) headersObj[key] = value;
  res.writeHead(webRes.status, headersObj);

  if (!webRes.body) {
    res.end();
    return;
  }

  const reader = webRes.body.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) res.write(Buffer.from(value));
    }
  } finally {
    reader.releaseLock();
  }
  res.end();
}

function summarizeToolText(content: unknown): string {
  if (!Array.isArray(content) || content.length === 0) return String(content);
  const first: any = content[0];
  return typeof first?.text === "string" ? first.text : JSON.stringify(first);
}
