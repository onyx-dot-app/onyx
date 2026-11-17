import { test, expect } from "@playwright/test";
import { loginAs, loginAsWorkerUser, apiLogin } from "@tests/e2e/utils/auth";
import { ensureOnboardingComplete } from "@tests/e2e/utils/chatActions";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  startMcpOauthServer,
  McpServerProcess,
} from "@tests/e2e/utils/mcpServer";
import { AdminMcpServersPage } from "@tests/e2e/pages/AdminMcpServersPage";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { ChatPluginsPopover } from "@tests/e2e/pages/ChatPluginsPopover";
import { IntegrationConnectPrompt } from "@tests/e2e/pages/IntegrationConnectPrompt";
import { MemberPluginDetailPage } from "@tests/e2e/pages/MemberPluginDetailPage";
import { MemberPluginsPage } from "@tests/e2e/pages/MemberPluginsPage";
import {
  McpOAuthFlow,
  getMcpOAuthConfig,
  type McpOAuthConfig,
} from "@tests/e2e/mcp/McpOAuthFlow";
import {
  expectMcpToolInvoked,
  qualifiedMcpToolName,
} from "@tests/e2e/mcp/mcpToolInvocation";

// Resolved lazily: Playwright loads every spec for every project, and jobs
// without the OAuth env never run this spec.
let _oauthConfig: McpOAuthConfig | null = null;
function oauthConfig(): McpOAuthConfig {
  return (_oauthConfig ??= getMcpOAuthConfig());
}

const MCP_OAUTH_FLOW_TEST_TIMEOUT_MS = Number(
  process.env.MCP_OAUTH_TEST_TIMEOUT_MS || 300_000
);
const TOOL_NAME = "tool_0";
// Onyx saves only https OAuth endpoints. The local mock issuer is http and
// supports dynamic client registration, so only a real issuer gets a client.
function manualOAuthClient(): {
  clientId: string;
  clientSecret: string;
} | null {
  if (!process.env.MCP_OAUTH_ISSUER?.startsWith("https://")) return null;
  return {
    clientId: oauthConfig().clientId,
    clientSecret: oauthConfig().clientSecret,
  };
}

function buildMcpServerUrl(baseUrl: string): string {
  const trimmed = baseUrl.replace(/\/+$/, "");
  return trimmed.endsWith("/mcp") ? trimmed : `${trimmed}/mcp`;
}

/**
 * An MCP server where each user signs in with OAuth. The admin adds it on the
 * integration pages; members connect from a plugin page and from chat; a
 * scoped manager adds one "For me" from the Plugins page.
 */
test.describe("MCP OAuth flows", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(MCP_OAUTH_FLOW_TEST_TIMEOUT_MS);

  let serverProcess: McpServerProcess | null = null;
  let serverUrl = buildMcpServerUrl(
    process.env.MCP_TEST_SERVER_URL || "http://127.0.0.1:8004/mcp"
  );
  let serverName = "";
  let integrationId: number | null = null;
  let pluginId = "";
  let agentId: number | null = null;
  let agentName = "";
  const createdIntegrationIds: number[] = [];
  const curators: { email: string; password: string; groupId: number }[] = [];
  let chatUser: { email: string; password: string } | null = null;

  test.beforeAll(async ({ browser }, workerInfo) => {
    if (workerInfo.project.name !== "admin") return;
    if (!process.env.MCP_TEST_SERVER_URL) {
      const basePort = Number(process.env.MCP_TEST_SERVER_PORT || "8004");
      serverProcess = await startMcpOauthServer({
        port: basePort + workerInfo.workerIndex,
        bindHost: process.env.MCP_TEST_SERVER_BIND_HOST,
        publicHost: process.env.MCP_TEST_SERVER_PUBLIC_HOST,
      });
      const explicitPublicUrl = process.env.MCP_TEST_SERVER_PUBLIC_URL;
      const { host, port } = serverProcess.address;
      serverUrl = buildMcpServerUrl(
        explicitPublicUrl ?? `http://${host}:${port}`
      );
    }

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);
    const password = "TestPassword123!";
    chatUser = { email: `pw-oauth-chat-${Date.now()}@example.com`, password };
    await adminClient.registerUser(chatUser.email, password);
    for (const suffix of ["a", "b"]) {
      const email = `pw-curator-${Date.now()}-${suffix}@example.com`;
      await adminClient.registerUser(email, password);
      const record = await adminClient.getUserByEmail(email);
      if (!record) throw new Error(`No user record for ${email}`);
      const groupId = await adminClient.createUserGroup(
        `Playwright Curator ${Date.now()}-${suffix}`,
        [record.id]
      );
      // The manager edge gives scoped manage:actions.
      await adminClient.setGroupManager(groupId, record.id);
      curators.push({ email, password, groupId });
    }
    await adminContext.close();
  });

  test.afterAll(async ({ browser }, workerInfo) => {
    if (workerInfo.project.name !== "admin") return;
    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);
    if (agentId !== null) await adminClient.deleteAgent(agentId);
    for (const id of createdIntegrationIds)
      await adminClient.deleteIntegration(id);
    for (const curator of curators)
      await adminClient.deleteUserGroup(curator.groupId);
    await adminContext.close();
    if (serverProcess) await serverProcess.stop();
  });

  test("Admin adds an OAuth MCP server and connects from its plugin page", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "admin", "Runs in the admin project");
    await page.context().clearCookies();
    await loginAs(page, "admin");

    serverName = `PW MCP OAuth ${Date.now()}`;
    const adminMcp = new AdminMcpServersPage(page);
    await adminMcp.goto();
    await adminMcp.openAddServerModal();
    await adminMcp.integrations.fillMcpServer({
      name: serverName,
      url: serverUrl,
    });
    await adminMcp.integrations.expectOAuthProbe();
    await adminMcp.integrations.selectSignIn("Each user signs in", "OAuth");
    const client = manualOAuthClient();
    if (client) {
      await adminMcp.integrations.fillOAuthClient(
        client.clientId,
        client.clientSecret
      );
    }
    await adminMcp.integrations.chooseOwner("For the organization");
    integrationId = await adminMcp.integrations.submit();
    createdIntegrationIds.push(integrationId);

    const adminClient = new OnyxApiClient(page.request);
    const detailResponse = await page.request.get(
      `/api/admin/integrations/${integrationId}`
    );
    const detail: { plugins: { plugin_id: string }[] } =
      await detailResponse.json();
    pluginId = detail.plugins[0]?.plugin_id ?? "";
    expect(pluginId).not.toBe("");

    // MCP actions load after a connection, so the admin connects first.
    const member = new MemberPluginDetailPage(page);
    await member.goto(pluginId, "Integrations");
    await member.expectStatus("Not connected");
    await new McpOAuthFlow(page, oauthConfig()).completeFlowInNewTab(() =>
      member.startConnect(serverName)
    );
    await member.expectStatus("Connected");

    await adminClient.refreshIntegrationActions(integrationId);
    // These tests cover OAuth and invocation, not approval.
    await adminClient.setIntegrationActionPolicies(integrationId, {
      [TOOL_NAME]: "allow",
    });
    agentName = `PW OAuth Agent ${Date.now()}`;
    agentId = await adminClient.createAgentWithPlugins(agentName, [pluginId], {
      isPublic: true,
    });
  });

  test("A member connects from a plugin page and uses the tool", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "admin", "Runs in the admin project");
    test.skip(integrationId === null, "The admin test must run first");
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const plugins = new MemberPluginsPage(page);
    await plugins.goto();
    await plugins.filter("Integrations");
    await plugins.openPlugin(serverName);
    const detail = new MemberPluginDetailPage(page);
    await detail.openTab("Integrations");
    if (await detail.connectButton(serverName).isVisible()) {
      await new McpOAuthFlow(page, oauthConfig()).completeFlowInNewTab(() =>
        detail.startConnect(serverName)
      );
    }
    await detail.expectStatus("Connected");

    await new ChatPage(page).gotoAgent(agentId!, agentName);
    await expectMcpToolInvoked(
      page,
      qualifiedMcpToolName(integrationId!, serverName, TOOL_NAME)
    );
  });

  test("A member connects from the chat connect prompt", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "admin", "Runs in the admin project");
    test.skip(integrationId === null, "The admin test must run first");
    await page.context().clearCookies();
    await apiLogin(page, chatUser!.email, chatUser!.password);
    await page.goto(`/app?agentId=${agentId}`);
    await ensureOnboardingComplete(page);

    const prompt = new IntegrationConnectPrompt(page);
    await prompt.expectCount(1);
    await new McpOAuthFlow(page, oauthConfig()).connectFromPrompt(
      prompt,
      serverName
    );

    const popover = new ChatPluginsPopover(page);
    await popover.expectConnected(serverName);
    await popover.close();
    await expectMcpToolInvoked(
      page,
      qualifiedMcpToolName(integrationId!, serverName, TOOL_NAME)
    );
  });

  test("A scoped manager adds a personal OAuth server that another manager cannot see", async ({
    page,
    browser,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "admin", "Runs in the admin project");
    const [owner, other] = curators;
    test.skip(!owner || !other, "The curators were not created");

    await page.context().clearCookies();
    await apiLogin(page, owner!.email, owner!.password);
    await page.goto("/app");
    await ensureOnboardingComplete(page);

    const plugins = new MemberPluginsPage(page);
    await plugins.goto();
    const personalName = `PW MCP Personal ${Date.now()}`;
    const created = await plugins.addMcpServer({
      name: personalName,
      url: serverUrl,
      oauth: { client: manualOAuthClient() },
    });
    createdIntegrationIds.push(created.integrationId);

    await plugins.goto();
    await plugins.expectPluginVisible(personalName);

    const otherContext = await browser.newContext();
    const otherPage = await otherContext.newPage();
    await apiLogin(otherPage, other!.email, other!.password);
    const otherIntegrations = new AdminMcpServersPage(otherPage).integrations;
    await otherIntegrations.goto();
    await otherIntegrations.expectIntegrationAbsent(personalName);
    const read = await otherPage.request.get(
      `/api/admin/integrations/${created.integrationId}`
    );
    expect([403, 404]).toContain(read.status());
    await otherContext.close();
  });
});
