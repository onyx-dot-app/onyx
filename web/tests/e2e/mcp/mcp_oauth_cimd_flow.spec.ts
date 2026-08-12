import { expect, test } from "@playwright/test";
import { ActionsPopover } from "@tests/e2e/pages/ActionsPopover";
import { AdminMcpServersPage } from "@tests/e2e/pages/AdminMcpServersPage";
import { getMcpOAuthConfig, McpOAuthFlow } from "@tests/e2e/mcp/McpOAuthFlow";
import { expectMcpToolInvoked } from "@tests/e2e/mcp/mcpToolInvocation";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const MCP_SERVER_NAME = "PW MCP CIMD";
const MCP_SERVER_DESCRIPTION = "Playwright CIMD-only OAuth server";
const MCP_AGENT_NAME = "PW CIMD Assistant";
const MCP_TOOL_NAME = "tool_0";

interface McpServerSummary {
  id: number;
  server_url: string;
}

interface MockOidcStatus {
  client_metadata_fetch_count: number;
  registration_request_count: number;
  last_client_id: string | null;
}

function mcpServerUrl(): string {
  const baseUrl =
    process.env.MCP_TEST_SERVER_URL || "http://host.docker.internal:8004/mcp";
  const trimmedUrl = baseUrl.replace(/\/+$/, "");
  return trimmedUrl.endsWith("/mcp") ? trimmedUrl : `${trimmedUrl}/mcp`;
}

function mockOidcStatusUrl(): string {
  const issuer = process.env.MCP_OAUTH_ISSUER;
  if (!issuer) {
    throw new Error("MCP_OAUTH_ISSUER is required for the CIMD OAuth test");
  }
  return `${issuer.replace(/\/+$/, "")}/test/status`;
}

test("Admin connects a CIMD-only OAuth server and invokes its tool @mcp-cimd", async ({
  page,
}) => {
  test.setTimeout(300_000);

  await page.context().clearCookies();
  await loginAs(page, "admin");

  const apiClient = new OnyxApiClient(page.request);
  const serverUrl = mcpServerUrl();
  const existingServers =
    (await apiClient.listMcpServers()) as McpServerSummary[];
  for (const server of existingServers) {
    if (server.server_url === serverUrl) {
      await apiClient.deleteMcpServer(server.id);
    }
  }

  let serverId: number | null = null;
  let agentId: number | null = null;

  try {
    const adminMcp = new AdminMcpServersPage(page);
    const oauthFlow = new McpOAuthFlow(page, getMcpOAuthConfig());

    await adminMcp.goto();
    await adminMcp.openAddServerModal();
    await adminMcp.fillServerDetails({
      name: MCP_SERVER_NAME,
      description: MCP_SERVER_DESCRIPTION,
      url: serverUrl,
    });
    serverId = await adminMcp.submitAddServer();

    await adminMcp.selectAuthMethod("OAuth");
    await oauthFlow.clickAndWaitForPossibleUrlChange(
      () => adminMcp.clickConnect(),
      "CIMD OAuth connect click"
    );
    await oauthFlow.completeFlow({
      expectReturnPathContains: "/admin/actions/mcp",
      confirmConnected: () => adminMcp.expectServerCard(MCP_SERVER_NAME),
    });

    await adminMcp.setCardToolEnabled(MCP_TOOL_NAME, true);
    const toolId = await apiClient.findMcpToolId(serverId, MCP_TOOL_NAME);
    agentId = await apiClient.createAgentWithMcpTools(
      MCP_AGENT_NAME,
      [toolId],
      {
        instructions: "Use the CIMD MCP tool.",
        description: "Playwright CIMD MCP assistant.",
      }
    );

    await page.goto(`/app?agentId=${agentId}`, { waitUntil: "load" });
    const actions = new ActionsPopover(page);
    await oauthFlow.reauthenticateFromChat(
      actions,
      MCP_SERVER_NAME,
      `/app?agentId=${agentId}`
    );
    await expectMcpToolInvoked(page, MCP_TOOL_NAME, toolId);

    const statusResponse = await page.request.get(mockOidcStatusUrl());
    expect(statusResponse.ok()).toBeTruthy();
    const status = (await statusResponse.json()) as MockOidcStatus;
    expect(status.client_metadata_fetch_count).toBeGreaterThanOrEqual(2);
    expect(status.registration_request_count).toBe(0);
    expect(status.last_client_id).toBe(
      `${getMcpOAuthConfig().appBaseUrl.replace(/\/+$/, "")}/api/mcp/oauth/client-metadata`
    );
  } finally {
    if (agentId !== null) {
      await apiClient.deleteAgent(agentId);
    }
    if (serverId !== null) {
      await apiClient.deleteMcpServer(serverId);
    }
  }
});
