import { test, expect } from "@playwright/test";
import { loginAs, apiLogin } from "@tests/e2e/utils/auth";
import { ensureOnboardingComplete } from "@tests/e2e/utils/chatActions";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  startMcpApiKeyServer,
  McpServerProcess,
} from "@tests/e2e/utils/mcpServer";
import { AdminMcpServersPage } from "@tests/e2e/pages/AdminMcpServersPage";
import { ChatPreferencesPage } from "@tests/e2e/pages/ChatPreferencesPage";
import { ActionsPopover } from "@tests/e2e/pages/ActionsPopover";
import { AgentEditorPage } from "@tests/e2e/pages/AgentEditorPage";
import {
  expectMcpToolInvoked,
  expectMcpToolNotInvoked,
} from "@tests/e2e/mcp/mcpToolInvocation";

const API_KEY = process.env.MCP_API_KEY || "test-api-key-12345";
const DEFAULT_PORT = Number(process.env.MCP_API_KEY_TEST_PORT || "8005");
const MCP_API_KEY_TEST_URL = process.env.MCP_API_KEY_TEST_URL;
const MCP_ASSERTED_TOOL_NAME = "tool_0";

/**
 * Default-agent MCP integration for an admin-shared (API key) server.
 *
 * Setup (the MCP server + its tools) is provisioned once via the API in
 * `beforeAll`; tests then drive only the UI surface under test. One UI
 * "create-flow" test is retained to keep the Add-Server + auth modal covered.
 */
test.describe("Default Agent MCP Integration", () => {
  test.describe.configure({ mode: "serial" });

  let serverProcess: McpServerProcess | null = null;
  let serverId: number;
  let serverName: string;
  let serverUrl: string;
  let basicUserEmail: string;
  let basicUserPassword: string;
  let createdProviderId: number | null = null;
  let assertedToolId: number;
  // A throwaway server created by the UI create-flow test; cleaned up in afterAll.
  let uiServerId: number | null = null;

  test.beforeAll(async ({ browser }) => {
    if (MCP_API_KEY_TEST_URL) {
      serverUrl = MCP_API_KEY_TEST_URL;
    } else {
      serverProcess = await startMcpApiKeyServer({
        port: DEFAULT_PORT,
        apiKey: API_KEY,
      });
      serverUrl = `http://${serverProcess.address.host}:${serverProcess.address.port}/mcp`;
    }

    serverName = `PW API Key Server ${Date.now()}`;

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);

    createdProviderId = await adminClient.ensurePublicProvider();

    // Remove any stale servers pointing at the same mock URL.
    try {
      const existingServers = await adminClient.listMcpServers();
      for (const server of existingServers) {
        if (server.server_url === serverUrl) {
          await adminClient.deleteMcpServer(server.id);
        }
      }
    } catch (error) {
      console.warn("Failed to cleanup existing MCP servers", error);
    }

    // Provision the shared server + tools via API (replaces UI-driven setup).
    serverId = await adminClient.createMcpServerWithAuth({
      name: serverName,
      description: "Shared API key MCP server (e2e)",
      server_url: serverUrl,
      auth_type: "API_TOKEN",
      auth_performer: "ADMIN",
      api_token: API_KEY,
    });
    await adminClient.discoverMcpTools(serverId);
    assertedToolId = await adminClient.findMcpToolId(
      serverId,
      MCP_ASSERTED_TOOL_NAME
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

    if (createdProviderId !== null) {
      await adminClient.deleteProvider(createdProviderId);
    }
    if (uiServerId) {
      await adminClient.deleteMcpServer(uiServerId);
    }
    if (serverId) {
      await adminClient.deleteMcpServer(serverId);
    }
    await adminContext.close();

    if (serverProcess) {
      await serverProcess.stop();
    }
  });

  test("Admin can create an API key MCP server through the UI", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const adminMcp = new AdminMcpServersPage(page);
    await adminMcp.goto();

    const uiServerName = `${serverName} (UI)`;
    await adminMcp.openAddServerModal();
    await adminMcp.fillServerDetails({
      name: uiServerName,
      description: "API key MCP server created via UI",
      url: serverUrl,
    });
    uiServerId = await adminMcp.submitAddServer();

    await adminMcp.selectAuthMethod("API Key");
    await adminMcp.selectApiKeyTab("admin");
    await adminMcp.fillApiToken(API_KEY);
    await adminMcp.clickConnect();

    await adminMcp.expectServerCard(uiServerName);
    await adminMcp.refreshTools();

    // Exercise the card-level tool toggle: disable then re-enable a tool.
    await adminMcp.setCardToolEnabled(MCP_ASSERTED_TOOL_NAME, false);
    await adminMcp.setCardToolEnabled(MCP_ASSERTED_TOOL_NAME, true);
  });

  test("Admin adds MCP tools to the default agent via chat preferences", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const chatPrefs = new ChatPreferencesPage(page);
    await chatPrefs.goto();
    await chatPrefs.enableServerTools(serverName);
  });

  test("Basic user can see and toggle MCP tools in the default agent", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);

    await page.goto("/app");
    await page.waitForURL("**/app**");
    await ensureOnboardingComplete(page);

    const actions = new ActionsPopover(page);
    await actions.expectServerVisible(serverName);
    await actions.openServer(serverName);

    // Toggle a tool off and back on.
    await actions.disableTool(MCP_ASSERTED_TOOL_NAME);
    await actions.enableTool(MCP_ASSERTED_TOOL_NAME);

    // Disable All then Enable All affect the whole server.
    await actions.disableAll();
    await expect(
      actions.popover.locator('[role="switch"][aria-checked="false"]')
    ).not.toHaveCount(0);
    await actions.enableAll();
  });

  test("Basic user can create an assistant with MCP actions attached", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);

    await page.goto("/app");
    await ensureOnboardingComplete(page);

    const editor = new AgentEditorPage(page);
    await editor.openFromSidebar();

    const agentName = `MCP Assistant ${Date.now()}`;
    await editor.fill({
      name: agentName,
      description: "Assistant with MCP actions attached.",
      instructions: `For secret-value requests, call ${MCP_ASSERTED_TOOL_NAME} and return its output exactly.`,
    });
    await editor.enableMcpServer(serverId);
    await editor.enableFirstMcpTool(serverId);
    const agentId = await editor.create();

    const client = new OnyxApiClient(page.request);
    const assistant = await client.getAssistant(agentId);
    expect(
      assistant.tools.some((tool) => tool.mcp_server_id === serverId)
    ).toBeTruthy();

    // The tool is enabled, so a forced call should actually invoke it.
    await expectMcpToolInvoked(page, MCP_ASSERTED_TOOL_NAME, assertedToolId);

    // Disable the tool from the actions popover and confirm it no longer runs.
    const actions = new ActionsPopover(page);
    await actions.openServer(serverName);
    await actions.searchTool(MCP_ASSERTED_TOOL_NAME);
    await actions.disableTool(MCP_ASSERTED_TOOL_NAME);
    await actions.close();

    await expectMcpToolNotInvoked(page, MCP_ASSERTED_TOOL_NAME, assertedToolId);
  });

  test("Admin can modify MCP tools in the default agent and changes persist", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const chatPrefs = new ChatPreferencesPage(page);
    await chatPrefs.goto();
    await chatPrefs.expandServerCard(serverName);

    const toolSwitch = chatPrefs.toolSwitch(MCP_ASSERTED_TOOL_NAME);
    await expect(toolSwitch).toBeVisible();
    const initialChecked = await toolSwitch.getAttribute("aria-checked");
    await chatPrefs.toggleTool(MCP_ASSERTED_TOOL_NAME);

    // Reload and confirm the new state persisted.
    await page.reload();
    await page.waitForURL("**/admin/configuration/chat-preferences**");
    await chatPrefs.expandServerCard(serverName);

    const toolSwitchAfter = chatPrefs.toolSwitch(MCP_ASSERTED_TOOL_NAME);
    await expect(toolSwitchAfter).toBeVisible();
    const expected = initialChecked === "true" ? "false" : "true";
    await expect(toolSwitchAfter).toHaveAttribute("aria-checked", expected);
  });

  test("Default agent instructions persist when saved via chat preferences", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const chatPrefs = new ChatPreferencesPage(page);
    await chatPrefs.goto();

    const testInstructions = `Test instructions for MCP - ${Date.now()}`;
    await chatPrefs.openModifyPrompt();
    await chatPrefs.fillSystemPrompt(testInstructions);
    await chatPrefs.saveSystemPrompt();

    // Reload and confirm the value persisted.
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.waitForURL("**/admin/configuration/chat-preferences**");

    await chatPrefs.openModifyPrompt();
    await chatPrefs.expectSystemPromptValue(testInstructions);
    await chatPrefs.cancelModifyPrompt();
  });

  test("MCP tools appear in a basic user's chat actions", async ({ page }) => {
    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);

    await page.goto("/app");
    await page.waitForURL("**/app**");

    const actions = new ActionsPopover(page);
    await actions.expectServerVisible(serverName);
    await actions.openServer(serverName);
    await expect(actions.toolSwitches).not.toHaveCount(0);
  });
});
