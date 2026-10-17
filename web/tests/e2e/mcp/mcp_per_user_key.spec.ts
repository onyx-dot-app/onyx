import { test, expect } from "@playwright/test";
import { loginAs, apiLogin } from "@tests/e2e/utils/auth";
import { ensureOnboardingComplete } from "@tests/e2e/utils/chatActions";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  startMcpPerUserKeyServer,
  McpServerProcess,
} from "@tests/e2e/utils/mcpServer";
import { AdminMcpServersPage } from "@tests/e2e/pages/AdminMcpServersPage";
import { ChatPluginsPopover } from "@tests/e2e/pages/ChatPluginsPopover";

// API keys baked into run_mcp_server_per_user_key.py. The script's middleware
// also requires every /mcp/* request to carry a non-empty `X-Username` header
// when launched with `--require-header X-Username`, which is exactly the
// scenario this spec exercises end-to-end.
const ADMIN_API_KEY =
  process.env.MCP_PER_USER_KEY_ADMIN_KEY ||
  "mcp_live-kid_alice_001-S3cr3tAlice";
const BASIC_USER_API_KEY =
  process.env.MCP_PER_USER_KEY_USER_KEY || "mcp_live-kid_bob_001-S3cr3tBob";
const ADMIN_USERNAME = "admin-pw";
const BASIC_USERNAME = "basic-pw";
const REQUIRED_USERNAME_HEADER = "X-Username";
const DEFAULT_PORT = Number(process.env.MCP_PER_USER_KEY_TEST_PORT || "8007");
const MCP_PER_USER_KEY_TEST_URL = process.env.MCP_PER_USER_KEY_TEST_URL;

const AUTH_TEMPLATE = {
  headers: {
    Authorization: "Bearer {api_key}",
    [REQUIRED_USERNAME_HEADER]: "{username}",
  },
  required_fields: ["api_key", "username"],
};

/**
 * MCP per-user API key auth with a multi-field credential template.
 *
 * The shared server is provisioned + attached to the default agent via the API
 * in `beforeAll`. One UI "create-flow" test exercises the multi-field header
 * builder; the remaining tests are the credential-gating regressions that must
 * run against the real UI.
 */
test.describe("MCP per-user API key auth (multi-field template)", () => {
  test.describe.configure({ mode: "serial" });

  let serverProcess: McpServerProcess | null = null;
  let serverId: number;
  let serverName: string;
  let serverUrl: string;
  let basicUserEmail: string;
  let basicUserPassword: string;
  let createdProviderId: number | null = null;
  // Throwaway server created by the UI create-flow test; cleaned up in afterAll.
  let uiServerId: number | null = null;

  test.beforeAll(async ({ browser }) => {
    if (MCP_PER_USER_KEY_TEST_URL) {
      serverUrl = MCP_PER_USER_KEY_TEST_URL;
    } else {
      serverProcess = await startMcpPerUserKeyServer({
        port: DEFAULT_PORT,
        requiredHeaders: [REQUIRED_USERNAME_HEADER],
      });
      serverUrl = `http://${serverProcess.address.host}:${serverProcess.address.port}/mcp`;
    }

    serverName = `PW Per-User Key Server ${Date.now()}`;

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);

    createdProviderId = await adminClient.ensurePublicProvider();

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

    // Provision the per-user template server (with the admin's own credentials)
    // and attach its tools to the default agent — all via API.
    serverId = await adminClient.createMcpServerWithAuth({
      name: serverName,
      description: "Per-user multi-field API key MCP server (e2e)",
      server_url: serverUrl,
      auth_type: "API_TOKEN",
      auth_performer: "PER_USER",
      auth_template: AUTH_TEMPLATE,
      admin_credentials: { api_key: ADMIN_API_KEY, username: ADMIN_USERNAME },
      admin_credentials_changed: { api_key: true, username: true },
    });
    const tools = await adminClient.discoverMcpTools(serverId);
    await adminClient.addToolsToDefaultAssistant(tools.map((tool) => tool.id));

    basicUserEmail = `pw-per-user-key-${Date.now()}@example.com`;
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

  test("Admin can configure a per-user server with two template fields via the UI", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const adminMcp = new AdminMcpServersPage(page);
    await adminMcp.goto();

    const uiServerName = `${serverName} (UI)`;
    await adminMcp.openAddServerModal();
    await adminMcp.enterServerUrlAndContinue(serverUrl);
    await adminMcp.selectAuthMethod("API Key");
    await adminMcp.selectApiKeyCredentials("per-user");

    // Header row 1 is pre-populated with Authorization / Bearer {api_key}.
    await adminMcp.expectFirstHeaderPrefilled();
    // Add a second row for the X-Username placeholder.
    await adminMcp.addHeaderRow();
    await adminMcp.fillHeaderRow(2, REQUIRED_USERNAME_HEADER, "{username}");

    // The "only for your own account" section reveals once placeholders are
    // detected. Fill the admin's own credentials so the backend can validate
    // against the live server during the upsert.
    await adminMcp.fillOwnCredentials({
      apiKey: ADMIN_API_KEY,
      username: ADMIN_USERNAME,
    });

    await adminMcp.fillServerDetails({
      name: uiServerName,
    });
    uiServerId = await adminMcp.connectAndWaitForCreation();

    await adminMcp.expectServerDetail(uiServerName);
    await adminMcp.refreshTools();
  });

  test("Basic user is prompted for every template field and can authenticate", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);

    await page.goto("/app");
    await page.waitForURL("**/app**");
    await ensureOnboardingComplete(page);

    const plugins = new ChatPluginsPopover(page);
    await plugins.connectPlugin(serverName);
    const dialog = plugins.connectionDialog;
    await dialog.expectFieldsVisible(["api_key", "username"]);

    await expect(dialog.connectButton).toBeDisabled();
    await dialog.fillField("api_key", BASIC_USER_API_KEY);
    await expect(dialog.connectButton).toBeDisabled();
    await dialog.fillField("username", BASIC_USERNAME);
    await expect(dialog.connectButton).toBeEnabled();
    await dialog.connectCredentials();

    await plugins.expectConnected(serverName);
    await plugins.expectPluginEnabled(serverName, true);
  });

  test("A saved personal connection keeps plugin selection available", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);

    await page.goto("/app");
    await page.waitForURL("**/app**");
    await ensureOnboardingComplete(page);

    const plugins = new ChatPluginsPopover(page);
    await plugins.expectConnected(serverName);
    await plugins.setPluginEnabled(serverName, false);
    await plugins.setPluginEnabled(serverName, true);
  });
});
