import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { describe, expect, it } from "vitest";

import { createMcpServer } from "../src/mcpServer.js";

const ENDERAI_TOOLS_WITH_ALIASES = [
  "enderai_request",
  "enderai_begin_document",
  "enderai_update_document",
  "enderai_finish_document",
  "enderai_session_info",
  "enderai_openapi",
  "enderai_health_check",
];

const TASKFORCE_CANONICAL_NAMES = ENDERAI_TOOLS_WITH_ALIASES.map((name) =>
  name.replace(/^enderai_/, "taskforce_"),
);

describe("MCP tool alias (TF-180)", () => {
  it("advertises both enderai_* and taskforce_* names in listTools", async () => {
    const server = createMcpServer();
    const [serverTransport, clientTransport] = InMemoryTransport.createLinkedPair();
    await server.connect(serverTransport);
    const client = new Client(
      { name: "test", version: "0" },
      { capabilities: {} },
    );
    await client.connect(clientTransport);

    const result = await client.listTools();
    const names = result.tools.map((t) => t.name);

    for (const enderaiName of ENDERAI_TOOLS_WITH_ALIASES) {
      expect(names).toContain(enderaiName);
    }
    for (const taskforceName of TASKFORCE_CANONICAL_NAMES) {
      expect(names).toContain(taskforceName);
    }
  });

  it("flags enderai_* descriptions as deprecated aliases", async () => {
    const server = createMcpServer();
    const [serverTransport, clientTransport] = InMemoryTransport.createLinkedPair();
    await server.connect(serverTransport);
    const client = new Client(
      { name: "test", version: "0" },
      { capabilities: {} },
    );
    await client.connect(clientTransport);

    const result = await client.listTools();
    const sessionInfoAlias = result.tools.find(
      (t) => t.name === "enderai_session_info",
    );
    const sessionInfoCanonical = result.tools.find(
      (t) => t.name === "taskforce_session_info",
    );
    expect(sessionInfoAlias?.description).toMatch(/Deprecated alias/);
    expect(sessionInfoCanonical?.description).not.toMatch(/Deprecated alias/);
  });

  it("calling taskforce_session_info reaches the enderai_session_info handler", async () => {
    const server = createMcpServer();
    const [serverTransport, clientTransport] = InMemoryTransport.createLinkedPair();
    await server.connect(serverTransport);
    const client = new Client(
      { name: "test", version: "0" },
      { capabilities: {} },
    );
    await client.connect(clientTransport);

    const result = await client.callTool({
      name: "taskforce_session_info",
      arguments: {},
    });

    expect(result.isError).not.toBe(true);
    const content = (result.content as Array<{ type: string; text?: string }>)[0];
    expect(content.type).toBe("text");
    const parsed = JSON.parse(content.text ?? "{}");
    // Same shape as enderai_session_info — confirms the alias hit the
    // existing handler rather than a stub.
    expect(parsed).toHaveProperty("policy_version");
    expect(parsed).toHaveProperty("workflow_model");
    expect(parsed.next).toHaveProperty("begin_tool");
  });
});
