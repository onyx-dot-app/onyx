import { test, expect } from "@playwright/test";
import { apiLogin } from "@tests/e2e/utils/auth";
import { ensureOnboardingComplete } from "@tests/e2e/utils/chatActions";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  startMcpPerUserKeyServer,
  McpServerProcess,
} from "@tests/e2e/utils/mcpServer";
import { ChatIntegrationsPopover } from "@tests/e2e/pages/ChatIntegrationsPopover";
import { IntegrationConnectPrompt } from "@tests/e2e/pages/IntegrationConnectPrompt";
import { CustomizeIntegrationPage } from "@tests/e2e/pages/CustomizeIntegrationPage";

// API keys baked into run_mcp_server_per_user_key.py. Launched with
// `--require-header X-Username`, the server also needs that header.
const ADMIN_API_KEY =
  process.env.MCP_PER_USER_KEY_ADMIN_KEY ||
  "mcp_live-kid_alice_001-S3cr3tAlice";
const MEMBER_API_KEY =
  process.env.MCP_PER_USER_KEY_USER_KEY || "mcp_live-kid_bob_001-S3cr3tBob";
const REQUIRED_USERNAME_HEADER = "X-Username";
const PORT = process.env.MCP_PER_USER_KEY_TEST_PORT
  ? Number(process.env.MCP_PER_USER_KEY_TEST_PORT)
  : undefined;
const MCP_PER_USER_KEY_TEST_URL = process.env.MCP_PER_USER_KEY_TEST_URL;
const FIELDS = { "API Key": MEMBER_API_KEY, Username: "basic-pw" };

/**
 * An MCP server where each user signs in with an API key and a user name. A
 * member connects it from the integration page and from the chat connect
 * prompt.
 */
test.describe("MCP per-user API key auth (two credential fields)", () => {
  test.describe.configure({ mode: "serial" });

  let serverProcess: McpServerProcess | null = null;
  let integrationId: number;
  let serverName: string;
  let serverUrl: string;
  let agentId: number | null = null;
  const users: { email: string; password: string }[] = [];
  let createdProviderId: number | null = null;

  test.beforeAll(async ({ browser }) => {
    if (MCP_PER_USER_KEY_TEST_URL) {
      serverUrl = MCP_PER_USER_KEY_TEST_URL;
    } else {
      serverProcess = await startMcpPerUserKeyServer({
        port: PORT,
        requiredHeaders: [REQUIRED_USERNAME_HEADER],
      });
      serverUrl = `http://${serverProcess.address.host}:${serverProcess.address.port}/mcp`;
    }
    serverName = `PW Per-User Key ${Date.now()}`;

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);
    createdProviderId = await adminClient.ensurePublicProvider();
    const created = await adminClient.createIntegration({
      for_organization: true,
      name: serverName,
      description: "Per-user API key MCP server (e2e)",
      auth_mode: "individual",
      auth_method: "api_key",
      credential_fields: [
        { key: "api_key", label: "API Key", secret: true },
        { key: "username", label: "Username", secret: false },
      ],
      header_template: {
        Authorization: "Bearer {api_key}",
        [REQUIRED_USERNAME_HEADER]: "{username}",
      },
      oauth_client: null,
      config: {
        shape: "mcp_server",
        server_url: serverUrl,
        transport: "STREAMABLE_HTTP",
      },
    });
    integrationId = created.id;
    // MCP actions load after a connection: the admin connects their own account.
    const connect = await adminContext.request.put(
      `/api/integrations/${integrationId}/connection`,
      { data: { fields: { api_key: ADMIN_API_KEY, username: "admin-pw" } } }
    );
    expect(connect.ok(), await connect.text()).toBeTruthy();
    await adminClient.refreshIntegrationActions(integrationId);
    // The connect prompt test chats with an agent that links the
    // integration. The default agent runs only the integrations that a member
    // turned on.
    agentId = await adminClient.createAgentWithIntegrations(
      `PW Per-User Key Agent ${Date.now()}`,
      [integrationId],
      { isPublic: true }
    );

    for (const name of ["page", "chat"]) {
      const email = `pw-per-user-${name}-${Date.now()}@example.com`;
      const password = "BasicUserPass123!";
      await adminClient.registerUser(email, password);
      users.push({ email, password });
    }
    await adminContext.close();
  });

  test.afterAll(async ({ browser }) => {
    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);
    if (agentId !== null) await adminClient.deleteAgent(agentId);
    if (integrationId) await adminClient.deleteIntegration(integrationId);
    if (createdProviderId !== null)
      await adminClient.deleteProvider(createdProviderId);
    await adminContext.close();
    if (serverProcess) await serverProcess.stop();
  });

  test("A member connects from the integration page with every credential field", async ({
    page,
  }) => {
    const member = users[0]!;
    await page.context().clearCookies();
    await apiLogin(page, member.email, member.password);

    const detail = new CustomizeIntegrationPage(page);
    await detail.goto(integrationId, "Configuration");
    await detail.expectStatus("Not connected");
    await detail.connectWithCredentials(serverName, FIELDS);
    await detail.expectStatus("Connected");

    await detail.disconnect(serverName);
    await detail.expectStatus("Not connected");
    await detail.connectWithCredentials(serverName, FIELDS);
  });

  test("A member connects from the chat connect prompt", async ({ page }) => {
    const member = users[1]!;
    await page.context().clearCookies();
    await apiLogin(page, member.email, member.password);
    await page.goto(`/app?agentId=${agentId}`);
    await ensureOnboardingComplete(page);

    const prompt = new IntegrationConnectPrompt(page);
    await prompt.expectCount(1);
    await prompt.open();
    await prompt.dialog.startConnect(serverName);
    await prompt.dialog.submitCredentials(FIELDS);
    await prompt.dialog.expectConnected(serverName);
    await prompt.dialog.close();
    await prompt.expectHidden();

    const popover = new ChatIntegrationsPopover(page);
    await popover.expectConnected(serverName);
    await popover.expectIntegrationEnabled(serverName, true);
  });
});
