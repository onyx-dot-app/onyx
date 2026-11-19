import { test, expect } from "@playwright/test";
import { loginAs, apiLogin } from "@tests/e2e/utils/auth";
import { ensureOnboardingComplete } from "@tests/e2e/utils/chatActions";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  startMcpApiKeyServer,
  McpServerProcess,
} from "@tests/e2e/utils/mcpServer";
import { AdminIntegrationsPage } from "@tests/e2e/pages/AdminIntegrationsPage";
import { AdminIntegrationDetailPage } from "@tests/e2e/pages/AdminIntegrationDetailPage";
import { ChatIntegrationsPopover } from "@tests/e2e/pages/ChatIntegrationsPopover";
import { CustomizePage } from "@tests/e2e/pages/CustomizePage";
import { CustomizeIntegrationPage } from "@tests/e2e/pages/CustomizeIntegrationPage";
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
 * An MCP server with one organization API key, available to the
 * organization. A member turns it on once; the default agent then uses it,
 * and the chat tools popover switches it for each agent.
 */
test.describe("Default Agent MCP Integration", () => {
  test.describe.configure({ mode: "serial" });

  let serverProcess: McpServerProcess | null = null;
  let integrationId: number;
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
    agentId = await adminClient.createAgentWithIntegrations(
      `PW MCP Agent ${Date.now()}`,
      [integrationId],
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
    const integrations = new AdminIntegrationsPage(page);
    const detail = new AdminIntegrationDetailPage(page);
    const uiName = `${serverName} (UI)`;
    await integrations.goto();
    await integrations.openAdd("MCP server");
    await integrations.fillMcpServer({ name: uiName, url: serverUrl });
    await integrations.selectSignIn(
      "One account for the organization",
      "API key"
    );
    await integrations.chooseOwner("For the organization");
    uiIntegrationId = await integrations.submit();
    await detail.connectOrganization({ "api key": API_KEY });
    await detail.expectLoaded(uiName);
    await detail.openTab("Actions");
    await detail.refreshActions();
  });

  test("A member sees the integration as connected on the Integrations tab", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);
    const customize = new CustomizePage(page);
    await customize.goto("Integrations");
    await customize.search(serverName);
    await customize.expectIntegrationState(serverName, "turn_on");
    await customize.openIntegration(serverName);

    const detail = new CustomizeIntegrationPage(page);
    await detail.openTab("Configuration");
    await detail.expectStatus("Connected");
    await expect(detail.disconnectButton(serverName)).toHaveCount(0);
  });

  // The default agent runs only the integrations that a member turned on.
  test("A member switches the integration in the default agent", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);
    const detail = new CustomizeIntegrationPage(page);
    await detail.goto(integrationId);
    await detail.setEnabled(serverName, true);

    await page.goto("/app");
    await ensureOnboardingComplete(page);

    const popover = new ChatIntegrationsPopover(page);
    await popover.expectIntegrationEnabled(serverName, true);
    await popover.setIntegrationEnabled(serverName, false);
    await popover.setIntegrationEnabled(serverName, true);
  });

  test("The agent calls the tool, and not after the member turns the integration off", async ({
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

    const popover = new ChatIntegrationsPopover(page);
    await popover.setIntegrationEnabled(serverName, false);
    await popover.close();
    await expectMcpToolNotInvoked(page, toolName, integrationId);
  });

  test("The member's choice for the agent persists in a new chat", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);
    await page.goto(`/app?agentId=${agentId}`);
    await ensureOnboardingComplete(page);

    const popover = new ChatIntegrationsPopover(page);
    await popover.expectIntegrationEnabled(serverName, false);
    await popover.setIntegrationEnabled(serverName, true);
  });
});
