import { test, expect } from "@playwright/test";
import { loginAs, apiLogin } from "@tests/e2e/utils/auth";
import { ensureOnboardingComplete } from "@tests/e2e/utils/chatActions";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  startMcpApiKeyServer,
  McpServerProcess,
} from "@tests/e2e/utils/mcpServer";
import { AdminMcpServersPage } from "@tests/e2e/pages/AdminMcpServersPage";
import { ChatPluginsPopover } from "@tests/e2e/pages/ChatPluginsPopover";
import { MemberPluginsPage } from "@tests/e2e/pages/MemberPluginsPage";
import { MemberPluginDetailPage } from "@tests/e2e/pages/MemberPluginDetailPage";
import {
  expectMcpToolInvoked,
  expectMcpToolNotInvoked,
  qualifiedMcpToolName,
} from "@tests/e2e/mcp/mcpToolInvocation";

const API_KEY = process.env.MCP_API_KEY || "test-api-key-12345";
const PORT = process.env.MCP_API_KEY_TEST_PORT
  ? Number(process.env.MCP_API_KEY_TEST_PORT)
  : undefined;
const MCP_API_KEY_TEST_URL = process.env.MCP_API_KEY_TEST_URL;
const MCP_ASSERTED_TOOL_NAME = "tool_0";

/**
 * An MCP server with one organization API key, in an Organization library
 * plugin. The default agent uses each plugin of the user, so a member sees it
 * on the Plugins page and in the chat tools popover with no setup.
 */
test.describe("Default Agent MCP Integration", () => {
  test.describe.configure({ mode: "serial" });

  let serverProcess: McpServerProcess | null = null;
  let integrationId: number;
  let pluginId: string;
  let serverName: string;
  let serverUrl: string;
  let basicUserEmail: string;
  let basicUserPassword: string;
  let createdProviderId: number | null = null;
  let agentId: number | null = null;
  let uiIntegrationId: number | null = null;

  test.beforeAll(async ({ browser }) => {
    if (MCP_API_KEY_TEST_URL) {
      serverUrl = MCP_API_KEY_TEST_URL;
    } else {
      serverProcess = await startMcpApiKeyServer({
        port: PORT,
        apiKey: API_KEY,
      });
      serverUrl = `http://${serverProcess.address.host}:${serverProcess.address.port}/mcp`;
    }
    serverName = `PW API Key ${Date.now()}`;

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);
    createdProviderId = await adminClient.ensurePublicProvider();

    const created = await adminClient.createIntegration({
      for_organization: true,
      name: serverName,
      description: "Shared API key MCP server (e2e)",
      auth_mode: "shared",
      auth_method: "api_key",
      credential_fields: [{ key: "api_key", label: "API Key", secret: true }],
      header_template: { Authorization: "Bearer {api_key}" },
      oauth_client: null,
      config: {
        shape: "mcp_server",
        server_url: serverUrl,
        transport: "STREAMABLE_HTTP",
      },
    });
    integrationId = created.id;
    const plugin = created.plugins[0];
    if (!plugin) throw new Error("The integration has no plugin");
    pluginId = plugin.plugin_id;
    const connect = await adminContext.request.put(
      `/api/admin/integrations/${integrationId}/organization-connection`,
      { data: { fields: { api_key: API_KEY } } }
    );
    expect(connect.ok(), await connect.text()).toBeTruthy();
    await adminClient.refreshIntegrationActions(integrationId);
    // These tests cover invocation, not approval (mcp_tool_approval.spec.ts).
    await adminClient.setIntegrationActionPolicies(integrationId, {
      [MCP_ASSERTED_TOOL_NAME]: "allow",
    });
    agentId = await adminClient.createAgentWithPlugins(
      `PW MCP Agent ${Date.now()}`,
      [pluginId],
      { isPublic: true }
    );

    basicUserEmail = `pw-basic-user-${Date.now()}@example.com`;
    basicUserPassword = "BasicUserPass123!";
    await adminClient.registerUser(basicUserEmail, basicUserPassword);
    await adminContext.close();
  });

  test.afterAll(async ({ browser }) => {
    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);
    if (agentId !== null) await adminClient.deleteAgent(agentId);
    if (uiIntegrationId !== null)
      await adminClient.deleteIntegration(uiIntegrationId);
    if (integrationId) await adminClient.deleteIntegration(integrationId);
    if (createdProviderId !== null)
      await adminClient.deleteProvider(createdProviderId);
    await adminContext.close();
    if (serverProcess) await serverProcess.stop();
  });

  test("Admin adds an MCP server through the integration pages", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const adminMcp = new AdminMcpServersPage(page);
    const uiName = `${serverName} (UI)`;
    await adminMcp.goto();
    await adminMcp.openAddServerModal();
    await adminMcp.integrations.fillMcpServer({ name: uiName, url: serverUrl });
    await adminMcp.integrations.selectSignIn(
      "One account for the organization",
      "API key"
    );
    await adminMcp.integrations.chooseOwner("For the organization");
    uiIntegrationId = await adminMcp.integrations.submit();
    await adminMcp.detail.connectOrganization({ "api key": API_KEY });
    await adminMcp.expectServerDetail(uiName);
    await adminMcp.refreshTools();
  });

  test("A member sees the plugin as connected on the Plugins page", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);
    const plugins = new MemberPluginsPage(page);
    await plugins.goto();
    await plugins.filter("Integrations");
    await plugins.search(serverName);
    await plugins.openPlugin(serverName);

    const detail = new MemberPluginDetailPage(page);
    await detail.expectTabs(["Overview", "Integrations"]);
    await detail.openTab("Integrations");
    await detail.expectStatus("Connected");
    await expect(detail.disconnectButton(serverName)).toHaveCount(0);
  });

  // The default agent runs only the plugins that a member turned on.
  test("A member switches the plugin in the default agent", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);
    const detail = new MemberPluginDetailPage(page);
    await detail.goto(pluginId);
    await detail.setPluginEnabled(serverName, true);

    await page.goto("/app");
    await ensureOnboardingComplete(page);

    const popover = new ChatPluginsPopover(page);
    await popover.expectPluginEnabled(serverName, true);
    await popover.setPluginEnabled(serverName, false);
    await popover.setPluginEnabled(serverName, true);
  });

  test("The agent calls the tool, and not after the member turns the plugin off", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);
    await page.goto(`/app?agentId=${agentId}`);
    await ensureOnboardingComplete(page);

    const toolName = qualifiedMcpToolName(
      integrationId,
      serverName,
      MCP_ASSERTED_TOOL_NAME
    );
    await expectMcpToolInvoked(page, toolName);

    const popover = new ChatPluginsPopover(page);
    await popover.setPluginEnabled(serverName, false);
    await popover.close();
    await expectMcpToolNotInvoked(page, toolName, pluginId);
  });

  test("The member's choice for the agent persists in a new chat", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);
    await page.goto(`/app?agentId=${agentId}`);
    await ensureOnboardingComplete(page);

    const popover = new ChatPluginsPopover(page);
    await popover.expectPluginEnabled(serverName, false);
    await popover.setPluginEnabled(serverName, true);
  });
});
