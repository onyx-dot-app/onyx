import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs, loginAsWorkerUser, apiLogin } from "@tests/e2e/utils/auth";
import { ensureOnboardingComplete } from "@tests/e2e/utils/chatActions";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  startMcpOauthServer,
  McpServerProcess,
} from "@tests/e2e/utils/mcpServer";
import { TEST_ADMIN_CREDENTIALS } from "@tests/e2e/constants";
import { AdminMcpServersPage } from "@tests/e2e/pages/AdminMcpServersPage";
import { ActionsPopover } from "@tests/e2e/pages/ActionsPopover";
import {
  McpOAuthFlow,
  getMcpOAuthConfig,
  type McpOAuthConfig,
} from "@tests/e2e/mcp/McpOAuthFlow";
import { expectMcpToolInvoked } from "@tests/e2e/mcp/mcpToolInvocation";

// Resolved lazily, not at import. Playwright loads every spec during collection
// for all projects, so calling getMcpOAuthConfig() at module scope would throw
// in jobs that don't set the OAuth env (e.g. the lite project) even though they
// never run this spec. Memoize on first use inside a test, preserving the
// fail-loudly behavior for the jobs that do run it.
let _oauthConfig: McpOAuthConfig | null = null;
function oauthConfig(): McpOAuthConfig {
  return (_oauthConfig ??= getMcpOAuthConfig());
}

const DEFAULT_MCP_SERVER_URL =
  process.env.MCP_TEST_SERVER_URL || "http://127.0.0.1:8004/mcp";
let runtimeMcpServerUrl = DEFAULT_MCP_SERVER_URL;

const MCP_OAUTH_FLOW_TEST_TIMEOUT_MS = Number(
  process.env.MCP_OAUTH_TEST_TIMEOUT_MS || 300_000
);

const TOOL_NAMES = { admin: "tool_0", curator: "tool_1" };

type Credentials = { email: string; password: string };

type FlowArtifacts = {
  serverId: number;
  serverName: string;
  agentId: number;
  agentName: string;
  toolName: string;
  toolId: number | null;
};

function buildMcpServerUrl(baseUrl: string): string {
  const trimmed = baseUrl.replace(/\/+$/, "");
  return trimmed.endsWith("/mcp") ? trimmed : `${trimmed}/mcp`;
}

/** Confirm the current session belongs to the expected user + role. */
async function verifySessionUser(
  page: Page,
  expected: { email: string; role: string }
): Promise<void> {
  const response = await page.request.get(`${oauthConfig().appBaseUrl}/api/me`);
  expect(response.ok()).toBeTruthy();
  const data = await response.json();
  expect(data.email).toBe(expected.email);
  expect(data.role).toBe(expected.role);
}

async function waitForUserRecord(
  client: OnyxApiClient,
  email: string,
  timeoutMs = 10_000
): Promise<{ id: string }> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const record = await client.getUserByEmail(email);
    if (record) {
      return record;
    }
    if (Date.now() >= deadline) {
      throw new Error(`Timed out waiting for user record ${email}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

/**
 * Create an OAuth MCP server through the admin UI, completing the IdP handshake,
 * and enable its tool on the server card. Returns the new server's id.
 */
async function configureOauthServer(
  page: Page,
  oauthFlow: McpOAuthFlow,
  options: {
    serverName: string;
    serverDescription: string;
    serverUrl: string;
    toolName: string;
  }
): Promise<number> {
  const adminMcp = new AdminMcpServersPage(page);
  await adminMcp.goto();
  await adminMcp.openAddServerModal();
  await adminMcp.fillServerDetails({
    name: options.serverName,
    description: options.serverDescription,
    url: options.serverUrl,
  });
  const serverId = await adminMcp.submitAddServer();

  await adminMcp.selectAuthMethod("OAuth");
  await adminMcp.fillOAuthCredentials(
    oauthConfig().clientId,
    oauthConfig().clientSecret
  );
  // Wait for the connect click to actually start the OAuth navigation before
  // handing off to completeFlow. Otherwise the page is still on
  // /admin/actions/mcp (which matches the return path) with the server name
  // already visible, and completeFlow's "already returned" early-out fires
  // before the IdP handshake even begins.
  await oauthFlow.clickAndWaitForPossibleUrlChange(
    () => adminMcp.clickConnect(),
    "OAuth connect click"
  );

  await oauthFlow.completeFlow({
    expectReturnPathContains: "/admin/actions/mcp",
    confirmConnected: async () => {
      await adminMcp.expectServerCard(options.serverName);
    },
  });

  await adminMcp.expectServerCard(options.serverName);
  await adminMcp.setCardToolEnabled(options.toolName, true);
  return serverId;
}

/** Confirm the server is present in chat, then prove the tool actually runs. */
async function verifyToolUsableFromChat(
  page: Page,
  artifacts: { serverName: string; toolName: string; toolId: number | null },
  agentId: number
): Promise<void> {
  const actions = new ActionsPopover(page);
  // Confirm the (now-authenticated) server is listed in the chat actions popover.
  await actions.ensureServerVisible(artifacts.serverName, { agentId });
  // Prove the tool is usable by forcing an invocation from chat. This is the
  // real end-to-end check (browser → backend → per-user OAuth token → mock
  // server → tool output) and the tool is attached to the agent via API, so it
  // runs regardless of the popover toggle. We deliberately do NOT drill into
  // the popover's tool list here: the OAuth server's row re-renders on
  // background auth-status revalidation and collapses the drilled-in view,
  // making in-popover tool assertions flaky. That drill-in UI is already
  // covered by the (stable) API-key and per-user-key specs.
  await expectMcpToolInvoked(page, artifacts.toolName, artifacts.toolId);
}

test.describe("MCP OAuth flows", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(MCP_OAUTH_FLOW_TEST_TIMEOUT_MS);

  let serverProcess: McpServerProcess | null = null;
  let adminArtifacts: FlowArtifacts | null = null;
  let curatorArtifacts: FlowArtifacts | null = null;
  let curatorCredentials: Credentials | null = null;
  let curatorTwoCredentials: Credentials | null = null;
  let curatorGroupId: number | null = null;
  let curatorTwoGroupId: number | null = null;

  test.beforeAll(async ({ browser }, workerInfo) => {
    if (workerInfo.project.name !== "admin") {
      return;
    }

    if (!process.env.MCP_TEST_SERVER_URL) {
      const basePort = Number(process.env.MCP_TEST_SERVER_PORT || "8004");
      serverProcess = await startMcpOauthServer({
        port: basePort + workerInfo.workerIndex,
        bindHost: process.env.MCP_TEST_SERVER_BIND_HOST,
        publicHost: process.env.MCP_TEST_SERVER_PUBLIC_HOST,
      });
      const explicitPublicUrl = process.env.MCP_TEST_SERVER_PUBLIC_URL;
      if (explicitPublicUrl) {
        runtimeMcpServerUrl = buildMcpServerUrl(explicitPublicUrl);
      } else {
        const { host, port } = serverProcess.address;
        runtimeMcpServerUrl = buildMcpServerUrl(`http://${host}:${port}`);
      }
    } else {
      runtimeMcpServerUrl = buildMcpServerUrl(process.env.MCP_TEST_SERVER_URL);
    }

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);

    try {
      const existingServers = await adminClient.listMcpServers();
      for (const server of existingServers) {
        if (server.server_url === runtimeMcpServerUrl) {
          await adminClient.deleteMcpServer(server.id);
        }
      }
    } catch (error) {
      console.warn("Failed to cleanup existing MCP servers", error);
    }

    const basePassword = "TestPassword123!";
    curatorCredentials = {
      email: `pw-curator-${Date.now()}@example.com`,
      password: basePassword,
    };
    await adminClient.registerUser(
      curatorCredentials.email,
      curatorCredentials.password
    );
    const curatorRecord = await waitForUserRecord(
      adminClient,
      curatorCredentials.email
    );
    curatorGroupId = await adminClient.createUserGroup(
      `Playwright Curator Group ${Date.now()}`,
      [curatorRecord.id]
    );
    await adminClient.setCuratorStatus(
      String(curatorGroupId),
      curatorRecord.id,
      true
    );

    curatorTwoCredentials = {
      email: `pw-curator-${Date.now()}-b@example.com`,
      password: basePassword,
    };
    await adminClient.registerUser(
      curatorTwoCredentials.email,
      curatorTwoCredentials.password
    );
    const curatorTwoRecord = await waitForUserRecord(
      adminClient,
      curatorTwoCredentials.email
    );
    curatorTwoGroupId = await adminClient.createUserGroup(
      `Playwright Curator Group ${Date.now()}-2`,
      [curatorTwoRecord.id]
    );
    await adminClient.setCuratorStatus(
      String(curatorTwoGroupId),
      curatorTwoRecord.id,
      true
    );

    await adminContext.close();
  });

  test.afterAll(async ({ browser }, workerInfo) => {
    if (workerInfo.project.name !== "admin") {
      return;
    }

    if (serverProcess) {
      await serverProcess.stop();
    }

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminClient = new OnyxApiClient(adminContext.request);

    if (adminArtifacts?.agentId) {
      await adminClient.deleteAgent(adminArtifacts.agentId);
    }
    if (adminArtifacts?.serverId) {
      await adminClient.deleteMcpServer(adminArtifacts.serverId);
    }
    if (curatorArtifacts?.agentId) {
      await adminClient.deleteAgent(curatorArtifacts.agentId);
    }
    if (curatorArtifacts?.serverId) {
      await adminClient.deleteMcpServer(curatorArtifacts.serverId);
    }
    if (curatorGroupId) {
      await adminClient.deleteUserGroup(curatorGroupId);
    }
    if (curatorTwoGroupId) {
      await adminClient.deleteUserGroup(curatorTwoGroupId);
    }

    await adminContext.close();
  });

  test("Admin can configure an OAuth MCP server and use tools end-to-end", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name !== "admin",
      "MCP OAuth flows run only in admin project"
    );

    await page.context().clearCookies();
    await loginAs(page, "admin");
    await verifySessionUser(page, {
      email: TEST_ADMIN_CREDENTIALS.email,
      role: "admin",
    });
    const adminClient = new OnyxApiClient(page.request);

    const oauthFlow = new McpOAuthFlow(page, oauthConfig());
    const serverName = `PW MCP Admin ${Date.now()}`;
    const agentName = `PW Admin Assistant ${Date.now()}`;

    const serverId = await configureOauthServer(page, oauthFlow, {
      serverName,
      serverDescription: "Playwright MCP OAuth server (admin)",
      serverUrl: runtimeMcpServerUrl,
      toolName: TOOL_NAMES.admin,
    });
    const adminToolId = await adminClient.findMcpToolId(
      serverId,
      TOOL_NAMES.admin
    );

    // Create the agent via API (private by default) rather than the editor UI.
    const agentId = await adminClient.createAgentWithMcpTools(
      agentName,
      [adminToolId],
      {
        instructions: "Assist with MCP OAuth testing.",
        description: "Playwright admin MCP assistant.",
      }
    );
    const createdAgent = await adminClient.getAssistant(agentId);
    expect(createdAgent.is_public).toBe(false);

    await page.goto(`/app?agentId=${agentId}`, { waitUntil: "load" });

    const artifacts = {
      serverName,
      toolName: TOOL_NAMES.admin,
      toolId: adminToolId,
    };

    // Per-user OAuth servers require the user to authenticate from chat before
    // their tools become usable: the admin-page "connect" only stores the
    // server's client config, not a per-user token for this user
    // (backend mcp/api.py: user_authenticated = get_user_connection_config(...)
    // is not None). So authenticate from chat first, then verify the tool runs.
    const actions = new ActionsPopover(page);
    await oauthFlow.reauthenticateFromChat(
      actions,
      serverName,
      `/app?agentId=${agentId}`
    );
    await verifyToolUsableFromChat(page, artifacts, agentId);

    // Server card is still present on the admin actions page.
    await page.goto("/admin/actions/mcp");
    await page.waitForURL("**/admin/actions/mcp**");
    await expect(
      page.getByText(serverName, { exact: false }).first()
    ).toBeVisible();

    // Publish the agent so the end-user flow can use it.
    await adminClient.updateAgentSharing(agentId, {
      isPublic: true,
      userIds: createdAgent.users.map((user) => user.id),
      groupIds: createdAgent.groups,
    });

    adminArtifacts = {
      serverId,
      serverName,
      agentId,
      agentName,
      toolName: TOOL_NAMES.admin,
      toolId: adminToolId,
    };
  });

  test("Curator flow with access isolation", async ({
    page,
    browser,
  }, testInfo) => {
    test.skip(
      testInfo.project.name !== "admin",
      "MCP OAuth flows run only in admin project"
    );
    test.skip(
      !curatorCredentials || !curatorTwoCredentials,
      "Curator credentials were not initialized"
    );

    await page.context().clearCookies();
    await apiLogin(
      page,
      curatorCredentials!.email,
      curatorCredentials!.password
    );
    await verifySessionUser(page, {
      email: curatorCredentials!.email,
      role: "curator",
    });
    const curatorClient = new OnyxApiClient(page.request);

    const oauthFlow = new McpOAuthFlow(page, oauthConfig());
    const serverName = `PW MCP Curator ${Date.now()}`;
    const agentName = `PW Curator Assistant ${Date.now()}`;

    let curatorServerProcess: McpServerProcess | null = null;
    let curatorServerUrl = runtimeMcpServerUrl;

    try {
      if (!process.env.MCP_TEST_SERVER_URL) {
        const basePort =
          (serverProcess?.address.port ??
            Number(process.env.MCP_TEST_SERVER_PORT || "8004")) + 1;
        curatorServerProcess = await startMcpOauthServer({ port: basePort });
        const { host, port } = curatorServerProcess.address;
        curatorServerUrl = `http://${host}:${port}/mcp`;
      }

      const serverId = await configureOauthServer(page, oauthFlow, {
        serverName,
        serverDescription: "Playwright MCP OAuth server (curator)",
        serverUrl: curatorServerUrl,
        toolName: TOOL_NAMES.curator,
      });
      const curatorToolId = await curatorClient.findMcpToolId(
        serverId,
        TOOL_NAMES.curator
      );

      const agentId = await curatorClient.createAgentWithMcpTools(
        agentName,
        [curatorToolId],
        {
          instructions: "Curator MCP OAuth assistant.",
          description: "Playwright curator MCP assistant.",
        }
      );

      await page.goto(`/app?agentId=${agentId}`, { waitUntil: "load" });
      // The curator is a freshly-registered user, so dismiss the "What should
      // Onyx call you?" onboarding modal before driving the chat UI (the admin
      // and worker users are already onboarded via global-setup).
      await ensureOnboardingComplete(page);

      // Per-user OAuth: the curator must authenticate from chat before the
      // server is usable (their admin-page connect only stores the server
      // client config, not a per-user token). Confirm the server is listed,
      // then authenticate, then confirm it's still listed (authenticated).
      // We don't drill into the popover tool list — that view re-renders on
      // background auth-status revalidation and is flaky for OAuth servers
      // (covered by the API-key / per-user-key specs instead).
      const actions = new ActionsPopover(page);
      await actions.ensureServerVisible(serverName, { agentId });

      await oauthFlow.reauthenticateFromChat(
        actions,
        serverName,
        `/app?agentId=${agentId}`
      );
      await actions.ensureServerVisible(serverName, { agentId });

      curatorArtifacts = {
        serverId,
        serverName,
        agentId,
        agentName,
        toolName: TOOL_NAMES.curator,
        toolId: curatorToolId,
      };

      // Isolation: a second curator must not be able to edit the first
      // curator's server.
      const curatorTwoContext = await browser.newContext();
      const curatorTwoPage = await curatorTwoContext.newPage();
      await apiLogin(
        curatorTwoPage,
        curatorTwoCredentials!.email,
        curatorTwoCredentials!.password
      );
      await curatorTwoPage.goto("/admin/actions/mcp");
      await expect(
        curatorTwoPage.getByText(serverName, { exact: false })
      ).not.toHaveCount(0);

      const editResponse = await curatorTwoPage.request.get(
        `${oauthConfig().appBaseUrl}/api/admin/mcp/servers/${serverId}`
      );
      expect(editResponse.status()).toBe(403);
      await curatorTwoContext.close();
    } finally {
      await curatorServerProcess?.stop().catch(() => {});
    }
  });

  test("End user can authenticate and invoke MCP tools via chat", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name !== "admin",
      "MCP OAuth flows run only in admin project"
    );
    test.skip(!adminArtifacts, "Admin flow must complete before user test");

    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const { agentId, serverName, toolName, toolId } = adminArtifacts!;

    await page.goto(`/app?agentId=${agentId}`, { waitUntil: "load" });

    const oauthFlow = new McpOAuthFlow(page, oauthConfig());
    const actions = new ActionsPopover(page);
    await actions.ensureServerVisible(serverName, { agentId });

    // The end user has not authenticated yet, so re-authenticating from chat
    // kicks off the OAuth handshake.
    await oauthFlow.reauthenticateFromChat(
      actions,
      serverName,
      `/app?agentId=${agentId}`
    );

    await verifyToolUsableFromChat(
      page,
      { serverName, toolName, toolId },
      agentId
    );
  });
});
