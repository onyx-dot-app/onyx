import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs, apiLogin } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  startMcpApiKeyServer,
  McpServerProcess,
} from "@tests/e2e/utils/mcpServer";
import {
  getPacketObjectsByType,
  sendMessageAndCaptureStreamPackets,
} from "@tests/e2e/utils/chatStream";

const API_KEY = process.env.MCP_API_KEY || "test-api-key-12345";
const DEFAULT_PORT = Number(process.env.MCP_API_KEY_TEST_PORT || "8005");
const MCP_API_KEY_TEST_URL = process.env.MCP_API_KEY_TEST_URL;
const MCP_ASSERTED_TOOL_NAME = "tool_0";

async function scrollToBottom(page: Page): Promise<void> {
  try {
    await page.evaluate(() => {
      window.scrollTo(0, document.body.scrollHeight);
    });
    await page.waitForTimeout(200);
  } catch {
    // ignore scrolling failures
  }
}

async function ensureOnboardingComplete(page: Page): Promise<void> {
  await page.evaluate(async () => {
    try {
      await fetch("/api/user/personalization", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ name: "Playwright User" }),
      });
    } catch {
      // ignore personalization failures
    }
  });

  await page.reload();
  await page.waitForLoadState("networkidle");
}

const getToolName = (packetObject: Record<string, unknown>): string | null => {
  const value = packetObject.tool_name;
  return typeof value === "string" ? value : null;
};

function getToolPacketCounts(
  packets: Record<string, unknown>[],
  toolName: string
): { start: number; delta: number; debug: number } {
  const start = getPacketObjectsByType(packets, "custom_tool_start").filter(
    (packetObject) => getToolName(packetObject) === toolName
  ).length;
  const delta = getPacketObjectsByType(packets, "custom_tool_delta").filter(
    (packetObject) => getToolName(packetObject) === toolName
  ).length;
  const debug = getPacketObjectsByType(packets, "tool_call_debug").filter(
    (packetObject) => getToolName(packetObject) === toolName
  ).length;

  return { start, delta, debug };
}

async function fetchMcpToolIdByName(
  page: Page,
  serverId: number,
  toolName: string
): Promise<number> {
  const response = await page.request.get(
    `/api/admin/mcp/server/${serverId}/db-tools`
  );
  expect(response.ok()).toBeTruthy();
  const data = (await response.json()) as {
    tools?: Array<{ id: number; name: string }>;
  };
  const matchedTool = data.tools?.find((tool) => tool.name === toolName);
  expect(matchedTool?.id).toBeTruthy();
  return matchedTool!.id;
}

test.describe("Default Assistant MCP Integration", () => {
  test.describe.configure({ mode: "serial" });

  let serverProcess: McpServerProcess | null = null;
  let serverId: number | null = null;
  let serverName: string;
  let serverUrl: string;
  let basicUserEmail: string;
  let basicUserPassword: string;
  let createdProviderId: number | null = null;
  let assertedToolId: number | null = null;

  test.beforeAll(async ({ browser }) => {
    // Use dockerized server if URL is provided, otherwise start local server
    if (MCP_API_KEY_TEST_URL) {
      serverUrl = MCP_API_KEY_TEST_URL;
      console.log(
        `[test-setup] Using dockerized MCP API key server at ${serverUrl}`
      );
    } else {
      // Start the MCP API key server locally
      serverProcess = await startMcpApiKeyServer({
        port: DEFAULT_PORT,
        apiKey: API_KEY,
      });
      serverUrl = `http://${serverProcess.address.host}:${serverProcess.address.port}/mcp`;
      console.log(
        `[test-setup] MCP API key server started locally at ${serverUrl}`
      );
    }

    serverName = `PW API Key Server ${Date.now()}`;

    // Setup as admin
    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminPage = await adminContext.newPage();
    const adminClient = new OnyxApiClient(adminPage.request);

    // Ensure a public LLM provider exists
    createdProviderId = await adminClient.ensurePublicProvider();

    // Clean up any existing servers with the same URL
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

    // Create a basic user for testing
    basicUserEmail = `pw-basic-user-${Date.now()}@example.com`;
    basicUserPassword = "BasicUserPass123!";
    await adminClient.registerUser(basicUserEmail, basicUserPassword);

    await adminContext.close();
  });

  test.afterAll(async ({ browser }) => {
    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminPage = await adminContext.newPage();
    const adminClient = new OnyxApiClient(adminPage.request);

    if (createdProviderId !== null) {
      await adminClient.deleteProvider(createdProviderId);
    }

    if (serverId) {
      await adminClient.deleteMcpServer(serverId);
    }

    await adminContext.close();

    // Only stop the server if we started it locally
    if (serverProcess) {
      await serverProcess.stop();
    }
  });

  test("Admin configures API key MCP server and adds tools to default assistant", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    console.log(`[test] Starting with server name: ${serverName}`);

    // Navigate to MCP actions page
    await page.goto("/admin/actions/mcp");
    await page.waitForURL("**/admin/actions/mcp**");
    console.log(`[test] Navigated to MCP actions page`);

    // Click "Add MCP Server" button to open modal
    await page.getByRole("button", { name: /Add MCP Server/i }).click();
    await page.waitForTimeout(500); // Wait for modal to appear
    console.log(`[test] Opened Add MCP Server modal`);

    // Fill basic server info in AddMCPServerModal
    await page.locator("input#name").fill(serverName);
    await page.locator("textarea#description").fill("Test API key MCP server");
    await page.locator("input#server_url").fill(serverUrl);
    console.log(`[test] Filled basic server details`);

    // Submit the modal to create server
    const createServerResponsePromise = page.waitForResponse((resp) => {
      try {
        const url = new URL(resp.url());
        return (
          url.pathname === "/api/admin/mcp/server" &&
          resp.request().method() === "POST" &&
          resp.ok()
        );
      } catch {
        return false;
      }
    });
    await page.getByRole("button", { name: "Add Server" }).click();
    const createServerResponse = await createServerResponsePromise;
    const createdServer = (await createServerResponse.json()) as {
      id?: number;
    };
    expect(createdServer.id).toBeTruthy();
    serverId = Number(createdServer.id);
    expect(serverId).toBeGreaterThan(0);
    console.log(`[test] Created MCP server with id: ${serverId}`);
    await page.waitForTimeout(1000); // Wait for modal to close and auth modal to open
    console.log(`[test] Created MCP server, auth modal should open`);

    // MCPAuthenticationModal should now be open - configure API Key authentication
    await page.waitForTimeout(500); // Ensure modal is fully rendered

    // Select API Key as authentication method
    const authMethodSelect = page.getByTestId("mcp-auth-method-select");
    await authMethodSelect.click();
    await page.getByRole("option", { name: "API Key" }).click();
    console.log(`[test] Selected API Key authentication method`);

    await page.waitForTimeout(500); // Wait for tabs to appear

    // The modal now shows tabs - select "Shared Key (Admin)" tab
    const adminTab = page.getByRole("tab", { name: /Shared Key.*Admin/i });
    await expect(adminTab).toBeVisible({ timeout: 5000 });
    await adminTab.click();
    await page.waitForTimeout(300);
    console.log(`[test] Selected Shared Key (Admin) tab`);

    // Wait for API token field to appear and fill it
    const apiTokenInput = page.locator('input[name="api_token"]');
    await expect(apiTokenInput).toBeVisible({ timeout: 10000 });
    await apiTokenInput.click(); // Focus the field first
    await apiTokenInput.fill(API_KEY);
    console.log(`[test] Filled API key`);

    // Click Connect button to submit authentication
    const connectButton = page.getByTestId("mcp-auth-connect-button");
    await expect(connectButton).toBeVisible({ timeout: 5000 });
    await connectButton.click();
    console.log(`[test] Clicked Connect button`);

    // Wait for the tools to be fetched
    await page.waitForTimeout(1000);
    console.log(`[test] Tools fetched successfully`);

    // Verify server card is visible
    await expect(
      page.getByText(serverName, { exact: false }).first()
    ).toBeVisible({ timeout: 20000 });
    console.log(`[test] Verified server card is visible`);

    // Click the refresh button to fetch/refresh tools
    const refreshButton = page.getByRole("button", { name: "Refresh tools" });
    await expect(refreshButton).toBeVisible({ timeout: 5000 });
    await refreshButton.click();
    console.log(`[test] Clicked refresh tools button`);

    // Wait for tools to load - "No tools available" should disappear
    await expect(page.getByText("No tools available")).not.toBeVisible({
      timeout: 15000,
    });
    console.log(`[test] Tools loaded successfully`);

    assertedToolId = await fetchMcpToolIdByName(
      page,
      serverId,
      MCP_ASSERTED_TOOL_NAME
    );
    console.log(
      `[test] Resolved ${MCP_ASSERTED_TOOL_NAME} to tool ID ${assertedToolId}`
    );

    // Disable multiple tools (tool_0, tool_1, tool_2, tool_3)
    const toolIds = ["tool_11", "tool_12", "tool_13", "tool_14"];
    let disabledToolsCount = 0;

    for (const toolId of toolIds) {
      const toolToggle = page.getByLabel(`tool-toggle-${toolId}`).first();

      // Check if the tool exists
      const isVisible = await toolToggle
        .isVisible({ timeout: 2000 })
        .catch(() => false);

      if (!isVisible) {
        console.log(`[test] Tool ${toolId} not found, skipping`);
        continue;
      }

      console.log(`[test] Found tool: ${toolId}`);

      // Disable if currently enabled (tools are enabled by default)
      const state = await toolToggle.getAttribute("aria-checked");
      if (state === "true") {
        await toolToggle.click();
        await expect(toolToggle).toHaveAttribute("aria-checked", "false", {
          timeout: 5000,
        });
        disabledToolsCount++;
        console.log(`[test] Disabled tool: ${toolId}`);
      } else {
        console.log(`[test] Tool ${toolId} already disabled`);
      }
    }

    console.log(
      `[test] Successfully disabled ${disabledToolsCount} tools via UI`
    );
  });

  test("Admin adds MCP tools to default assistant via default assistant page", async ({
    page,
  }) => {
    test.skip(!serverId, "MCP server must be created first");

    await page.context().clearCookies();
    await loginAs(page, "admin");
    console.log(`[test] Logged in as admin for default assistant config`);

    // Navigate to default assistant page
    await page.goto("/admin/configuration/default-assistant");
    await page.waitForURL("**/admin/configuration/default-assistant**");
    console.log(`[test] Navigated to default assistant page`);

    // Wait for page to load
    await expect(page.locator('[aria-label="admin-page-title"]')).toBeVisible({
      timeout: 10000,
    });
    console.log(`[test] Page loaded`);

    // Scroll to actions section
    await page.evaluate(() => {
      window.scrollTo(0, document.body.scrollHeight);
    });
    await page.waitForTimeout(300);

    // Find the MCP server section
    const mcpServerSection = page.getByTestId(`mcp-server-section-${serverId}`);
    await expect(mcpServerSection).toBeVisible({ timeout: 10000 });
    console.log(`[test] MCP server section found for server ID ${serverId}`);

    // Scroll section into view
    await mcpServerSection.scrollIntoViewIfNeeded();

    // Expand the MCP server if collapsed
    const toggleButton = page.getByTestId(`mcp-server-toggle-${serverId}`);
    const isExpanded = await toggleButton.getAttribute("aria-expanded");
    console.log(`[test] MCP server section expanded: ${isExpanded}`);
    if (isExpanded === "false") {
      await toggleButton.click();
      await page.waitForTimeout(300);
      console.log(`[test] Expanded MCP server section`);
    }

    // Select the MCP server checkbox (to enable all tools)
    const serverCheckbox = mcpServerSection.getByRole("checkbox", {
      name: "mcp-server-select-all-tools-checkbox",
    });
    await expect(serverCheckbox).toBeVisible({ timeout: 5000 });
    await serverCheckbox.scrollIntoViewIfNeeded();
    if ((await serverCheckbox.getAttribute("aria-checked")) !== "true") {
      await serverCheckbox.click();
    }
    await expect(serverCheckbox).toHaveAttribute("aria-checked", "true");
    console.log(`[test] Checked MCP server checkbox`);

    // Scroll to bottom to find Save button
    await scrollToBottom(page);

    // Save the form
    const saveButton = page.getByRole("button", { name: "Save Changes" });
    await expect(saveButton).toBeVisible({ timeout: 5000 });
    await saveButton.scrollIntoViewIfNeeded();
    await saveButton.click();
    console.log(`[test] Clicked Save Changes`);

    // Wait for success message
    await expect(page.getByText(/successfully/i)).toBeVisible({
      timeout: 10000,
    });

    console.log(`[test] MCP tools successfully added to default assistant`);
  });

  test("Basic user can see and toggle MCP tools in default assistant", async ({
    page,
  }) => {
    test.skip(!serverId, "MCP server must be configured first");
    test.skip(!basicUserEmail, "Basic user must be created first");

    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);
    console.log(`[test] Logged in as basic user: ${basicUserEmail}`);

    // Navigate to chat (which uses default assistant for new users)
    await page.goto("/app");
    await page.waitForURL("**/app**");
    await ensureOnboardingComplete(page);
    console.log(`[test] Navigated to chat page`);

    // Open actions popover
    const actionsButton = page.getByTestId("action-management-toggle");
    await expect(actionsButton).toBeVisible({ timeout: 10000 });
    await actionsButton.click();
    console.log(`[test] Opened actions popover`);

    // Wait for popover to open
    const popover = page.locator('[data-testid="tool-options"]');
    await expect(popover).toBeVisible({ timeout: 5000 });

    // Find the MCP server in the list
    const serverLineItem = popover
      .locator(".group\\/LineItem")
      .filter({ hasText: serverName });
    await expect(serverLineItem).toBeVisible({ timeout: 10000 });
    console.log(`[test] Found MCP server: ${serverName}`);

    // Click to open the server's tool list
    await serverLineItem.click();
    await page.waitForTimeout(500);
    console.log(`[test] Clicked on MCP server to view tools`);

    // Verify we're in the tool list view (should have Enable/Disable All)
    await expect(
      popover.getByText(/(Enable|Disable) All/i).first()
    ).toBeVisible({ timeout: 5000 });
    console.log(`[test] Tool list view loaded`);

    // Find a specific tool (tool_0)
    const toolLineItem = popover
      .locator(".group\\/LineItem")
      .filter({ hasText: /^tool_0/ })
      .first();
    await expect(toolLineItem).toBeVisible({ timeout: 5000 });
    console.log(`[test] Found tool: tool_0`);

    // Find the toggle switch for the tool
    const toolToggle = toolLineItem.locator('[role="switch"]');
    await expect(toolToggle).toBeVisible({ timeout: 5000 });
    console.log(`[test] Tool toggle is visible`);

    // Get initial state and toggle
    const initialState = await toolToggle.getAttribute("aria-checked");
    console.log(`[test] Initial toggle state: ${initialState}`);
    await toolToggle.click();
    await page.waitForTimeout(300);

    // Wait for state to change
    const expectedState = initialState === "true" ? "false" : "true";
    await expect(toolToggle).toHaveAttribute("aria-checked", expectedState, {
      timeout: 5000,
    });
    console.log(`[test] Toggle state changed to: ${expectedState}`);

    // Toggle back
    await toolToggle.click();
    await page.waitForTimeout(300);
    await expect(toolToggle).toHaveAttribute("aria-checked", initialState!, {
      timeout: 5000,
    });
    console.log(`[test] Toggled back to original state: ${initialState}`);

    // Test "Disable All" functionality
    const disableAllButton = popover.getByText(/Disable All/i).first();
    const hasDisableAll = await disableAllButton.isVisible();
    console.log(`[test] Disable All button visible: ${hasDisableAll}`);

    if (hasDisableAll) {
      await disableAllButton.click();
      await page.waitForTimeout(500);

      // Verify at least one toggle is now unchecked
      const anyUnchecked = await popover
        .locator('[role="switch"][aria-checked="false"]')
        .count();
      expect(anyUnchecked).toBeGreaterThan(0);
      console.log(`[test] Disabled all tools (${anyUnchecked} unchecked)`);
    }

    // Test "Enable All" functionality
    const enableAllButton = popover.getByText(/Enable All/i).first();
    const hasEnableAll = await enableAllButton.isVisible();
    console.log(`[test] Enable All button visible: ${hasEnableAll}`);

    if (hasEnableAll) {
      await enableAllButton.click();
      await page.waitForTimeout(500);
      console.log(`[test] Enabled all tools`);
    }

    console.log(`[test] Basic user completed MCP tool management tests`);
  });

  test("Basic user can create assistant with MCP actions attached", async ({
    page,
  }) => {
    test.skip(!serverId, "MCP server must be configured first");
    test.skip(!basicUserEmail, "Basic user must be created first");
    test.skip(!assertedToolId, "MCP asserted tool ID must be resolved first");

    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);

    await page.goto("/app");
    await ensureOnboardingComplete(page);
    await page.getByTestId("AppSidebar/more-agents").click();
    await page.waitForURL("**/app/agents");

    await page
      .getByTestId("AgentsPage/new-agent-button")
      .getByRole("link", { name: "New Agent" })
      .click();
    await page.waitForURL("**/app/agents/create");

    const assistantName = `MCP Assistant ${Date.now()}`;
    await page.locator('input[name="name"]').fill(assistantName);
    await page
      .locator('textarea[name="description"]')
      .fill("Assistant with MCP actions attached.");
    await page
      .locator('textarea[name="instructions"]')
      .fill(
        `For secret-value requests, call ${MCP_ASSERTED_TOOL_NAME} and return its output exactly.`
      );

    const mcpServerSwitch = page.locator(
      `button[role="switch"][name="mcp_server_${serverId}.enabled"]`
    );
    await mcpServerSwitch.scrollIntoViewIfNeeded();
    await mcpServerSwitch.click();
    await expect(mcpServerSwitch).toHaveAttribute("aria-checked", "true");

    const firstToolToggle = page
      .locator(`button[role="switch"][name^="mcp_server_${serverId}.tool_"]`)
      .first();
    await expect(firstToolToggle).toBeVisible({ timeout: 15000 });
    const toolState = await firstToolToggle.getAttribute("aria-checked");
    if (toolState !== "true") {
      await firstToolToggle.click();
    }
    await expect(firstToolToggle).toHaveAttribute("aria-checked", "true");

    await page.getByRole("button", { name: "Create" }).click();

    await page.waitForURL(/.*\/app\?assistantId=\d+.*/);
    const assistantIdMatch = page.url().match(/assistantId=(\d+)/);
    expect(assistantIdMatch).toBeTruthy();
    const assistantId = assistantIdMatch ? assistantIdMatch[1] : null;
    expect(assistantId).not.toBeNull();

    const client = new OnyxApiClient(page.request);
    const assistant = await client.getAssistant(Number(assistantId));
    const hasMcpTool = assistant.tools.some(
      (tool) => tool.mcp_server_id === serverId
    );
    expect(hasMcpTool).toBeTruthy();

    const invocationPackets = await sendMessageAndCaptureStreamPackets(
      page,
      `Call ${MCP_ASSERTED_TOOL_NAME} with {"name":"pw-invoke-${Date.now()}"} and return only the tool output.`,
      {
        mockLlmResponse: JSON.stringify({
          name: MCP_ASSERTED_TOOL_NAME,
          arguments: { name: `pw-invoke-${Date.now()}` },
        }),
        payloadOverrides: {
          forced_tool_id: assertedToolId,
          forced_tool_ids: [assertedToolId],
        },
        waitForAiMessage: false,
      }
    );
    const invocationCounts = getToolPacketCounts(
      invocationPackets,
      MCP_ASSERTED_TOOL_NAME
    );
    expect(invocationCounts.start).toBeGreaterThan(0);
    expect(invocationCounts.delta).toBeGreaterThan(0);
    expect(invocationCounts.debug).toBeGreaterThan(0);

    const actionsButton = page.getByTestId("action-management-toggle");
    await expect(actionsButton).toBeVisible({ timeout: 10000 });
    await actionsButton.click();

    const popover = page.locator('[data-testid="tool-options"]');
    await expect(popover).toBeVisible({ timeout: 5000 });

    const serverLineItem = popover
      .locator(".group\\/LineItem")
      .filter({ hasText: serverName })
      .first();
    await expect(serverLineItem).toBeVisible({ timeout: 10000 });
    await serverLineItem.click();

    const toolSearchInput = popover
      .getByPlaceholder(/Search .* tools/i)
      .first();
    await expect(toolSearchInput).toBeVisible({ timeout: 10000 });
    await toolSearchInput.fill(MCP_ASSERTED_TOOL_NAME);

    const toolToggle = popover.getByLabel(`Toggle ${MCP_ASSERTED_TOOL_NAME}`);
    await expect(toolToggle).toBeVisible({ timeout: 10000 });
    const isToolToggleUnchecked = async () => {
      const dataState = await toolToggle.getAttribute("data-state");
      if (typeof dataState === "string") {
        return dataState === "unchecked";
      }
      return (await toolToggle.getAttribute("aria-checked")) === "false";
    };
    if (!(await isToolToggleUnchecked())) {
      await toolToggle.click();
    }
    await expect
      .poll(isToolToggleUnchecked, {
        timeout: 5000,
      })
      .toBe(true);

    await page.keyboard.press("Escape").catch(() => {});

    const disabledPackets = await sendMessageAndCaptureStreamPackets(
      page,
      `Call ${MCP_ASSERTED_TOOL_NAME} with {"name":"pw-disabled-${Date.now()}"} and return only the tool output.`,
      {
        mockLlmResponse: JSON.stringify({
          name: MCP_ASSERTED_TOOL_NAME,
          arguments: { name: `pw-disabled-${Date.now()}` },
        }),
        payloadOverrides: {
          forced_tool_id: assertedToolId,
          forced_tool_ids: [assertedToolId],
        },
        waitForAiMessage: false,
      }
    );
    const disabledCounts = getToolPacketCounts(
      disabledPackets,
      MCP_ASSERTED_TOOL_NAME
    );
    expect(disabledCounts.start).toBe(0);
    expect(disabledCounts.delta).toBe(0);
    expect(disabledCounts.debug).toBe(0);
  });

  test("Admin can modify MCP tools in default assistant", async ({ page }) => {
    test.skip(!serverId, "MCP server must be configured first");

    await page.context().clearCookies();
    await loginAs(page, "admin");
    console.log(`[test] Testing tool modification`);

    // Navigate to default assistant page
    await page.goto("/admin/configuration/default-assistant");
    await page.waitForURL("**/admin/configuration/default-assistant**");

    // Scroll to actions section
    await scrollToBottom(page);

    // Find the MCP server section
    const mcpServerSection = page.getByTestId(`mcp-server-section-${serverId}`);
    await expect(mcpServerSection).toBeVisible({ timeout: 10000 });
    await mcpServerSection.scrollIntoViewIfNeeded();

    // Expand if needed
    const toggleButton = page.getByTestId(`mcp-server-toggle-${serverId}`);
    const isExpanded = await toggleButton.getAttribute("aria-expanded");
    if (isExpanded === "false") {
      await toggleButton.click();
      await page.waitForTimeout(300);
      console.log(`[test] Expanded MCP server section`);
    }

    // Find a specific tool checkbox
    const firstToolCheckbox = mcpServerSection.getByLabel(
      `mcp-server-tool-checkbox-tool_0`
    );

    await expect(firstToolCheckbox).toBeVisible({ timeout: 5000 });
    await firstToolCheckbox.scrollIntoViewIfNeeded();

    // Get initial state and toggle
    const initialChecked = await firstToolCheckbox.getAttribute("aria-checked");
    console.log(`[test] Initial tool state: ${initialChecked}`);
    await firstToolCheckbox.click();
    await page.waitForTimeout(300);

    // Scroll to Save button
    await scrollToBottom(page);

    // Save changes
    const saveButton = page.getByRole("button", { name: "Save Changes" });
    await expect(saveButton).toBeVisible({ timeout: 5000 });
    await saveButton.scrollIntoViewIfNeeded();
    await saveButton.click();
    console.log(`[test] Clicked Save Changes`);

    // Wait for success
    await expect(page.getByText(/successfully/i)).toBeVisible({
      timeout: 10000,
    });
    console.log(`[test] Save successful`);

    // Reload and verify persistence
    await page.reload();
    await page.waitForURL("**/admin/configuration/default-assistant**");
    await scrollToBottom(page);

    // Re-find the section
    const mcpServerSectionAfter = page.getByTestId(
      `mcp-server-section-${serverId}`
    );
    await expect(mcpServerSectionAfter).toBeVisible({ timeout: 10000 });
    await mcpServerSectionAfter.scrollIntoViewIfNeeded();

    // Re-expand the section
    const toggleButtonAfter = page.getByTestId(`mcp-server-toggle-${serverId}`);
    const isExpandedAfter =
      await toggleButtonAfter.getAttribute("aria-expanded");
    if (isExpandedAfter === "false") {
      await toggleButtonAfter.click();
      await page.waitForTimeout(300);
    }

    // Verify the tool state persisted
    const firstToolCheckboxAfter = mcpServerSectionAfter.getByLabel(
      `mcp-server-tool-checkbox-tool_0`
    );
    await expect(firstToolCheckboxAfter).toBeVisible({ timeout: 5000 });
    const finalChecked =
      await firstToolCheckboxAfter.getAttribute("aria-checked");
    console.log(`[test] Final tool state: ${finalChecked}`);
    expect(finalChecked).not.toEqual(initialChecked);
  });

  test("Instructions persist when saving default assistant", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    await page.goto("/admin/configuration/default-assistant");
    await page.waitForURL("**/admin/configuration/default-assistant**");

    // Find the instructions textarea
    const instructionsTextarea = page.locator("textarea").first();
    await expect(instructionsTextarea).toBeVisible({ timeout: 5000 });
    await instructionsTextarea.scrollIntoViewIfNeeded();

    const testInstructions = `Test instructions for MCP - ${Date.now()}`;
    await instructionsTextarea.fill(testInstructions);
    console.log(`[test] Filled instructions`);

    // Scroll to Save button
    await scrollToBottom(page);

    // Save changes
    const saveButton = page.getByRole("button", { name: "Save Changes" });
    await expect(saveButton).toBeVisible({ timeout: 5000 });
    await saveButton.scrollIntoViewIfNeeded();
    await saveButton.click();

    await expect(page.getByText(/successfully/i)).toBeVisible({
      timeout: 10000,
    });
    console.log(`[test] Instructions saved successfully`);

    // Reload and verify
    await page.reload();
    await page.waitForURL("**/admin/configuration/default-assistant**");

    const instructionsTextareaAfter = page.locator("textarea").first();
    await expect(instructionsTextareaAfter).toBeVisible({ timeout: 5000 });
    await expect(instructionsTextareaAfter).toHaveValue(testInstructions);

    console.log(`[test] Instructions persisted correctly`);
  });

  test("MCP tools appear in basic user's chat actions after being added to default assistant", async ({
    page,
  }) => {
    test.skip(!serverId, "MCP server must be configured first");
    test.skip(!basicUserEmail, "Basic user must be created first");

    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);
    console.log(`[test] Logged in as basic user to verify tool visibility`);

    // Navigate to chat
    await page.goto("/app");
    await page.waitForURL("**/app**");
    console.log(`[test] Navigated to chat`);

    // Open actions popover
    const actionsButton = page.getByTestId("action-management-toggle");
    await expect(actionsButton).toBeVisible({ timeout: 10000 });
    await actionsButton.click();
    console.log(`[test] Opened actions popover`);

    // Wait for popover
    const popover = page.locator('[data-testid="tool-options"]');
    await expect(popover).toBeVisible({ timeout: 5000 });

    // Verify MCP server appears in the actions list
    const serverLineItem = popover
      .locator(".group\\/LineItem")
      .filter({ hasText: serverName });
    await expect(serverLineItem).toBeVisible({ timeout: 10000 });
    console.log(`[test] Found MCP server in actions list`);

    // Click to see tools
    await serverLineItem.click();
    await page.waitForTimeout(500);
    console.log(`[test] Clicked server to view tools`);

    // Verify tools are present
    const toolsList = popover.locator('[role="switch"]');
    const toolCount = await toolsList.count();
    expect(toolCount).toBeGreaterThan(0);

    console.log(
      `[test] Basic user can see ${toolCount} MCP tools from default assistant`
    );
  });
});
