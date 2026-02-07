import path from "node:path";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

async function main(): Promise<void> {
  const baseUrl = (process.env.ENDERAI_BASE_URL ?? "https://enderai-backend.onrender.com").trim();
  const bearerToken = process.env.ENDERAI_BEARER_TOKEN?.trim();
  const timeoutMs = (process.env.ENDERAI_TIMEOUT_MS ?? "30000").trim();

  const __filename = fileURLToPath(import.meta.url);
  const __dirname = path.dirname(__filename);

  const distIndex = path.resolve(__dirname, "..", "dist", "index.js");

  const transport = new StdioClientTransport({
    command: "node",
    args: [distIndex],
    env: {
      ENDERAI_BASE_URL: baseUrl,
      ...(bearerToken ? { ENDERAI_BEARER_TOKEN: bearerToken } : {}),
      ENDERAI_TIMEOUT_MS: timeoutMs,
    },
    stderr: "inherit",
    cwd: path.resolve(__dirname, ".."),
  });

  const client = new Client({ name: "enderai-api-smoke", version: "0.0.0" });
  await client.connect(transport);

  const tools = await client.listTools();
  const toolNames = tools.tools.map((t) => t.name).sort();
  // eslint-disable-next-line no-console
  console.log("tools:", toolNames.join(", "));

  const health = await client.callTool({ name: "enderai_health_check", arguments: {} });
  // eslint-disable-next-line no-console
  console.log("enderai_health_check:", summarizeToolText(health.content));

  const openapi = await client.callTool({ name: "enderai_openapi", arguments: {} });
  // eslint-disable-next-line no-console
  console.log("enderai_openapi:", summarizeToolText(openapi.content));

  await client.close();
}

function summarizeToolText(content: unknown): string {
  // Our server returns a single `text` item containing JSON string.
  if (!Array.isArray(content) || content.length === 0) return String(content);
  const first: any = content[0];
  const text = typeof first?.text === "string" ? first.text : JSON.stringify(first);
  const oneLine = text.replace(/\s+/g, " ").trim();
  return oneLine.length > 220 ? `${oneLine.slice(0, 220)}...` : oneLine;
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error(err);
  process.exit(1);
});
