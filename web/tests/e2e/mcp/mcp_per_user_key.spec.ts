import { test, expect } from "@playwright/test";
import { loginAs, apiLogin } from "@tests/e2e/utils/auth";
import { ensureOnboardingComplete } from "@tests/e2e/utils/chatActions";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  startMcpPerUserKeyServer,
  McpServerProcess,
} from "@tests/e2e/utils/mcpServer";
import { AdminMcpServersPage } from "@tests/e2e/pages/AdminMcpServersPage";
import { ActionsPopover } from "@tests/e2e/pages/ActionsPopover";

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
    await adminMcp.fillServerDetails({
      name: uiServerName,
      description: "Test per-user multi-field API key MCP server",
      url: serverUrl,
    });
    uiServerId = await adminMcp.submitAddServer();

    await adminMcp.selectAuthMethod("API Key");
    // Per-user is the default tab for API Key; click it explicitly so the test
    // fails loudly if that default ever changes.
    await adminMcp.selectApiKeyTab("per-user");

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

    await adminMcp.connectAndWaitForUpsert();

    await adminMcp.expectServerCard(uiServerName);
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

    const actions = new ActionsPopover(page);
    await actions.expectServerVisible(serverName);

    // Clicking before authenticating opens the credentials modal.
    await actions.clickServer(serverName);

    const modal = actions.credentialsModal;
    await modal.expectOpen(/Enter Credentials/i);

    // === The actual regression check ===
    // Both required fields must render. Before the `required_fields`
    // persistence fix, only `api_key` showed and the user could submit without
    // `username`, leaving the literal `{username}` in the X-Username header.
    await modal.expectFieldsVisible();

    // The save button stays disabled until both fields are non-empty.
    await expect(modal.saveButton).toBeVisible();
    await expect(modal.saveButton).toBeDisabled();
    await modal.fillApiKey(BASIC_USER_API_KEY);
    await expect(modal.saveButton).toBeDisabled();
    await modal.fillUsername(BASIC_USERNAME);
    await expect(modal.saveButton).toBeEnabled();

    await modal.save();

    // Now authenticated: clicking the row drills into the tool list instead of
    // reopening the auth modal. The popover closed with the modal, so reopen.
    await actions.openServer(serverName);
  });

  test("Re-authenticate row exposes the multi-field modal with the same gating", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);

    await page.goto("/app");
    await page.waitForURL("**/app**");
    await ensureOnboardingComplete(page);

    const actions = new ActionsPopover(page);
    await actions.expectServerVisible(serverName);

    // Already authenticated from the previous test, so this drills into tools.
    await actions.openServer(serverName);
    await actions.clickReauthRow();

    const modal = actions.credentialsModal;
    await modal.expectOpen(/Manage Credentials/i);
    await modal.expectFieldsVisible();

    // Gating still enforces "all-or-nothing".
    await modal.fillApiKey("");
    await modal.fillUsername("");
    await expect(modal.updateButton).toBeDisabled();
    await modal.fillApiKey(BASIC_USER_API_KEY);
    await expect(modal.updateButton).toBeDisabled();
    await modal.fillUsername(BASIC_USERNAME);
    await expect(modal.updateButton).toBeEnabled();
  });
});
