import type { Page } from "@playwright/test";
import { MCPTransportType, type MCPSetupProbeResult } from "@/lib/mcp/types";

export async function mockPublicMcpProbe(page: Page): Promise<void> {
  const result: MCPSetupProbeResult = {
    kind: "public",
    transport: MCPTransportType.STREAMABLE_HTTP,
    tool_count: 0,
    server_name: "Test MCP server",
  };
  await page.route("**/api/admin/mcp/probe", async (route) => {
    await route.fulfill({
      contentType: "application/x-ndjson",
      body: `${JSON.stringify({ type: "result", result })}\n`,
    });
  });
}
