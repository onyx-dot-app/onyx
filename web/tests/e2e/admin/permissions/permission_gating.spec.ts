import { test, expect } from "./fixtures";
import { Permission } from "@/lib/types";
import { apiLogin, loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

test.describe("Permission gating — ADD_AGENTS", () => {
  test("New Agent button is disabled without ADD_AGENTS and enabled after granting it", async ({
    page,
    adminClient,
    testUserContext,
  }) => {
    const registryResponse = await page.request.get(
      "/api/manage/admin/permissions/registry"
    );
    test.skip(
      registryResponse.status() === 404,
      "Permission registry unavailable (CE environment)"
    );

    const { groupId, email, password } = testUserContext;

    // Phase 1: Without permission — button should be disabled
    await page.context().clearCookies();
    await apiLogin(page, email, password);
    await page.goto("/app/agents");
    await page.waitForLoadState("networkidle");

    const newAgentButton = page.getByLabel("AgentsPage/new-agent-button");
    await expect(newAgentButton).toBeVisible();
    await expect(newAgentButton).toBeDisabled();

    // Phase 2: Grant ADD_AGENTS — button should become enabled
    await page.context().clearCookies();
    await loginAs(page, "admin");
    await adminClient.setUserGroupPermissions(groupId, [Permission.ADD_AGENTS]);

    await page.context().clearCookies();
    await apiLogin(page, email, password);
    await page.goto("/app/agents");
    await page.waitForLoadState("networkidle");

    await expect(newAgentButton).toBeVisible();
    await expect(newAgentButton).toBeEnabled();

    // Phase 3: Revoke ADD_AGENTS — button should be disabled again
    await page.context().clearCookies();
    await loginAs(page, "admin");
    await adminClient.setUserGroupPermissions(groupId, []);

    await page.context().clearCookies();
    await apiLogin(page, email, password);
    await page.goto("/app/agents");
    await page.waitForLoadState("networkidle");

    await expect(newAgentButton).toBeVisible();
    await expect(newAgentButton).toBeDisabled();
  });
});

test.describe("Permission gating — MANAGE_AGENTS", () => {
  test("Admin panel and /admin/agents are gated behind MANAGE_AGENTS", async ({
    page,
    adminClient,
    testUserContext,
  }) => {
    const registryResponse = await page.request.get(
      "/api/manage/admin/permissions/registry"
    );
    test.skip(
      registryResponse.status() === 404,
      "Permission registry unavailable (CE environment)"
    );

    const { groupId, email, password } = testUserContext;

    // Admin creates a custom agent
    const agentName = `E2E Manage Agent ${Date.now()}`;
    const agentId = await adminClient.createAgent(agentName, "Test agent");

    try {
      // Phase 1: Without MANAGE_AGENTS — /admin/agents should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/agents");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Phase 2: Grant MANAGE_AGENTS — /admin/agents should be accessible
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, [
        Permission.MANAGE_AGENTS,
      ]);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/agents");
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain("/admin/agents");
      await expect(page.getByRole("link", { name: "New Agent" })).toBeVisible({
        timeout: 10000,
      });
      await expect(page.getByText(agentName)).toBeVisible();

      // Phase 3: Revoke MANAGE_AGENTS — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/agents");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      // Cleanup: delete the agent
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const cleanupClient = new OnyxApiClient(page.request);
      await cleanupClient.deleteAgent(agentId);
    }
  });
});

test.describe("Permission gating — MANAGE_LLMS", () => {
  test("Admin panel and /admin/configuration/llm are gated behind MANAGE_LLMS", async ({
    page,
    adminClient,
    testUserContext,
  }) => {
    const registryResponse = await page.request.get(
      "/api/manage/admin/permissions/registry"
    );
    test.skip(
      registryResponse.status() === 404,
      "Permission registry unavailable (CE environment)"
    );

    const { groupId, email, password } = testUserContext;

    // Admin creates an LLM provider
    const providerName = `E2E Manage LLM ${Date.now()}`;
    const providerId = await adminClient.createProvider(providerName);

    try {
      // Phase 1: Without MANAGE_LLMS — /admin/configuration/llm should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/configuration/llm");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Phase 2: Grant MANAGE_LLMS — /admin/configuration/llm should be accessible
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, [
        Permission.MANAGE_LLMS,
      ]);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/configuration/llm");
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain("/admin/configuration/llm");
      await expect(
        page.getByLabel("admin-page-title").getByText("Language Models")
      ).toBeVisible({
        timeout: 10000,
      });
      await expect(page.getByText(providerName)).toBeVisible();

      // Phase 3: Revoke MANAGE_LLMS — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/configuration/llm");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      // Cleanup: delete the provider
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const cleanupClient = new OnyxApiClient(page.request);
      await cleanupClient.deleteProvider(providerId);
    }
  });
});

test.describe("Permission gating — MANAGE_CONNECTORS", () => {
  test("Admin panel and /admin/indexing/status are gated behind MANAGE_CONNECTORS", async ({
    page,
    adminClient,
    testUserContext,
  }) => {
    const registryResponse = await page.request.get(
      "/api/manage/admin/permissions/registry"
    );
    test.skip(
      registryResponse.status() === 404,
      "Permission registry unavailable (CE environment)"
    );

    const { groupId, email, password } = testUserContext;

    // Admin creates a file connector
    const connectorName = `E2E Manage Connector ${Date.now()}`;
    const ccPairId = await adminClient.createFileConnector(connectorName);

    try {
      // Phase 1: Without MANAGE_CONNECTORS — /admin/indexing/status should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/indexing/status");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Also verify /admin/add-connector redirects
      await page.goto("/admin/add-connector");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Phase 2: Grant MANAGE_CONNECTORS — /admin/indexing/status should be accessible
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, [
        Permission.MANAGE_CONNECTORS,
      ]);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/indexing/status");
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain("/admin/indexing/status");
      await expect(
        page.getByLabel("admin-page-title").getByText("Existing Connectors")
      ).toBeVisible({ timeout: 10000 });
      await expect(page.getByRole("table")).toBeVisible();

      // Also verify /admin/add-connector is accessible
      await page.goto("/admin/add-connector");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/admin/add-connector");
      await expect(
        page.getByLabel("admin-page-title").getByText("Add Connector")
      ).toBeVisible({ timeout: 10000 });

      // Phase 3: Revoke MANAGE_CONNECTORS — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/indexing/status");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      // Cleanup: delete the connector
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const cleanupClient = new OnyxApiClient(page.request);
      await cleanupClient.deleteCCPair(ccPairId);
    }
  });
});

test.describe("Permission gating — MANAGE_DOCUMENT_SETS", () => {
  test("Admin panel and /admin/documents/sets are gated behind MANAGE_DOCUMENT_SETS, with implied READ_CONNECTORS", async ({
    page,
    adminClient,
    testUserContext,
  }) => {
    const registryResponse = await page.request.get(
      "/api/manage/admin/permissions/registry"
    );
    test.skip(
      registryResponse.status() === 404,
      "Permission registry unavailable (CE environment)"
    );

    const { groupId, email, password } = testUserContext;

    // Admin creates a public file connector
    const connectorName = `E2E DocSet Connector ${Date.now()}`;
    const ccPairId = await adminClient.createFileConnector(
      connectorName,
      "public"
    );

    // Admin creates a second user group (user is already in fixture group;
    // having 2 groups causes the full group selector to render)
    const extraGroupName = `E2E DocSet Group ${Date.now()}`;
    const extraGroupId = await adminClient.createUserGroup(extraGroupName, [
      testUserContext.userId,
    ]);

    try {
      // Phase 1: Without MANAGE_DOCUMENT_SETS — /admin/documents/sets should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/documents/sets");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Also verify /admin/documents/sets/new redirects
      await page.goto("/admin/documents/sets/new");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Phase 2: Grant MANAGE_DOCUMENT_SETS — pages should be accessible
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, [
        Permission.MANAGE_DOCUMENT_SETS,
      ]);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/documents/sets");
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain("/admin/documents/sets");
      await expect(
        page.getByLabel("admin-page-title").getByText("Document Sets")
      ).toBeVisible({ timeout: 10000 });
      await expect(page.getByText("New Document Set")).toBeVisible();

      // Navigate to creation page to verify implied READ_CONNECTORS
      await page.goto("/admin/documents/sets/new");
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain("/admin/documents/sets/new");
      await expect(
        page.getByLabel("admin-page-title").getByText("New Document Set")
      ).toBeVisible({ timeout: 10000 });

      // Open the connector dropdown and verify the admin-created connector is listed
      const connectorSearchInput = page.getByTestId("connector-search-input");
      await expect(connectorSearchInput).toBeVisible({ timeout: 10000 });
      await connectorSearchInput.click();

      // Verify the connector is visible (proves implied READ_CONNECTORS)
      await expect(page.getByText(connectorName)).toBeVisible({
        timeout: 10000,
      });

      // Verify group selector loaded successfully (proves implied READ_USER_GROUPS)
      await expect(
        page.getByText("Assign group access for this document set")
      ).toBeVisible({ timeout: 10000 });
      await expect(
        page.getByText(
          "Failed to load assign group access for this document set"
        )
      ).not.toBeVisible();

      // Open the group dropdown and verify the extra group is listed
      const groupSearchInput = page.getByTestId("groups-search-input");
      await expect(groupSearchInput).toBeVisible({ timeout: 10000 });
      await groupSearchInput.click();
      await expect(
        page.getByRole("option", { name: extraGroupName })
      ).toBeVisible({
        timeout: 10000,
      });

      // Phase 3: Revoke MANAGE_DOCUMENT_SETS — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/documents/sets");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      // Cleanup: delete the connector and extra group
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const cleanupClient = new OnyxApiClient(page.request);
      await cleanupClient.deleteCCPair(ccPairId);
      await cleanupClient.deleteUserGroup(extraGroupId);
    }
  });
});

test.describe("Permission gating — MANAGE_ACTIONS", () => {
  test("Admin panel /admin/actions/mcp and /admin/actions/open-api are gated behind MANAGE_ACTIONS", async ({
    page,
    adminClient,
    testUserContext,
  }) => {
    const registryResponse = await page.request.get(
      "/api/manage/admin/permissions/registry"
    );
    test.skip(
      registryResponse.status() === 404,
      "Permission registry unavailable (CE environment)"
    );

    const { groupId, email, password } = testUserContext;

    // Admin creates an OpenAPI custom tool and an MCP server
    const toolName = `E2E Manage Tool ${Date.now()}`;
    const toolId = await adminClient.createCustomTool(toolName);

    const mcpName = `E2E Manage MCP ${Date.now()}`;
    const mcpServerId = await adminClient.createMcpServer(mcpName);

    try {
      // Phase 1: Without MANAGE_ACTIONS — both pages should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/actions/open-api");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      await page.goto("/admin/actions/mcp");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Phase 2: Grant MANAGE_ACTIONS — both pages should be accessible
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, [
        Permission.MANAGE_ACTIONS,
      ]);

      await page.context().clearCookies();
      await apiLogin(page, email, password);

      // Verify OpenAPI Actions page and created tool visibility
      await page.goto("/admin/actions/open-api");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/admin/actions/open-api");
      await expect(
        page.getByLabel("admin-page-title").getByText("OpenAPI Actions")
      ).toBeVisible({ timeout: 10000 });
      await expect(
        page.getByLabel(`${toolName} OpenAPI action card`)
      ).toBeVisible({ timeout: 10000 });

      // Verify MCP Actions page and created server visibility
      await page.goto("/admin/actions/mcp");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/admin/actions/mcp");
      await expect(
        page.getByLabel("admin-page-title").getByText("MCP Actions")
      ).toBeVisible({ timeout: 10000 });
      await expect(page.getByLabel(`${mcpName} MCP server card`)).toBeVisible({
        timeout: 10000,
      });

      // Phase 3: Revoke MANAGE_ACTIONS — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/actions/open-api");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      await page.goto("/admin/actions/mcp");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      // Cleanup: delete the tool and MCP server
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const cleanupClient = new OnyxApiClient(page.request);
      await cleanupClient.deleteCustomTool(toolId);
      await cleanupClient.deleteMcpServer(mcpServerId);
    }
  });
});

test.describe("Permission gating — MANAGE_SERVICE_ACCOUNT_API_KEYS", () => {
  test("Admin panel /admin/service-accounts is gated behind MANAGE_SERVICE_ACCOUNT_API_KEYS, with implied READ_USER_GROUPS", async ({
    page,
    adminClient,
    testUserContext,
  }) => {
    const registryResponse = await page.request.get(
      "/api/manage/admin/permissions/registry"
    );
    test.skip(
      registryResponse.status() === 404,
      "Permission registry unavailable (CE environment)"
    );

    const { groupId, email, password } = testUserContext;

    // Admin creates a service account
    const accountName = `E2E Service Account ${Date.now()}`;
    const apiKeyId = await adminClient.createServiceAccount(accountName);

    // Admin creates a second user group (so the groups dropdown has content to render)
    const extraGroupName = `E2E SvcAcct Group ${Date.now()}`;
    const extraGroupId = await adminClient.createUserGroup(extraGroupName);

    try {
      // Phase 1: Without MANAGE_SERVICE_ACCOUNT_API_KEYS — /admin/service-accounts should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/service-accounts");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Phase 2: Grant MANAGE_SERVICE_ACCOUNT_API_KEYS — /admin/service-accounts should be accessible
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, [
        Permission.MANAGE_SERVICE_ACCOUNT_API_KEYS,
      ]);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/service-accounts");
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain("/admin/service-accounts");
      await expect(
        page
          .getByLabel("admin-page-title")
          .getByText("Service Accounts", { exact: true })
      ).toBeVisible({ timeout: 10000 });
      await expect(page.getByText(accountName)).toBeVisible();

      // Click "New Service Account" to open the creation modal
      await page.getByText("New Service Account").click();
      await expect(
        page.getByText("Create Service Account", { exact: true })
      ).toBeVisible({ timeout: 10000 });

      // Open the groups search dropdown and verify the extra group is listed
      // (proves implied READ_USER_GROUPS)
      const groupsSearchInput = page.getByTestId("groups-search-input");
      await expect(groupsSearchInput).toBeVisible({ timeout: 10000 });
      await groupsSearchInput.click();
      await expect(page.getByText(extraGroupName).first()).toBeVisible({
        timeout: 10000,
      });

      // Phase 3: Revoke MANAGE_SERVICE_ACCOUNT_API_KEYS — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/service-accounts");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      // Cleanup: delete the service account and extra group
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const cleanupClient = new OnyxApiClient(page.request);
      await cleanupClient.deleteServiceAccount(apiKeyId);
      await cleanupClient.deleteUserGroup(extraGroupId);
    }
  });
});

test.describe("Permission gating — MANAGE_BOTS", () => {
  test("Admin panel /admin/bots and /admin/discord-bot are gated behind MANAGE_BOTS", async ({
    page,
    adminClient,
    testUserContext,
  }) => {
    const registryResponse = await page.request.get(
      "/api/manage/admin/permissions/registry"
    );
    test.skip(
      registryResponse.status() === 404,
      "Permission registry unavailable (CE environment)"
    );

    const { groupId, email, password } = testUserContext;

    // Admin creates a Discord guild (Slack bot skipped — creation requires real Slack API tokens)
    const guild = await adminClient.createDiscordGuild();

    try {
      // Phase 1: Without MANAGE_BOTS — both pages should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/bots");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      await page.goto("/admin/discord-bot");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Phase 2: Grant MANAGE_BOTS — both pages should be accessible
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, [
        Permission.MANAGE_BOTS,
      ]);

      await page.context().clearCookies();
      await apiLogin(page, email, password);

      // Verify Slack Integration page
      await page.goto("/admin/bots");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/admin/bots");
      await expect(
        page.getByLabel("admin-page-title").getByText("Slack Integration")
      ).toBeVisible({ timeout: 10000 });
      await expect(
        page.getByRole("button", { name: "New Slack Bot" })
      ).toBeVisible();

      // Verify Discord Integration page
      await page.goto("/admin/discord-bot");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/admin/discord-bot");
      await expect(
        page.getByLabel("admin-page-title").getByText("Discord Integration")
      ).toBeVisible({ timeout: 10000 });
      await expect(page.getByText("Add Server")).toBeVisible();

      // Phase 3: Revoke MANAGE_BOTS — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/bots");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      await page.goto("/admin/discord-bot");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      // Cleanup: delete the Discord guild
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const cleanupClient = new OnyxApiClient(page.request);
      await cleanupClient.deleteDiscordGuild(guild.id);
    }
  });
});

test.describe("Permission gating — READ_QUERY_HISTORY", () => {
  test("Admin panel /admin/performance/query-history is gated behind READ_QUERY_HISTORY", async ({
    page,
    adminClient,
    testUserContext,
  }) => {
    const registryResponse = await page.request.get(
      "/api/manage/admin/permissions/registry"
    );
    test.skip(
      registryResponse.status() === 404,
      "Permission registry unavailable (CE environment)"
    );

    const { groupId, email, password } = testUserContext;

    // Admin creates a chat session so the query history table has data
    const sessionDescription = `E2E Query History ${Date.now()}`;
    const chatSessionId =
      await adminClient.createChatSession(sessionDescription);

    try {
      // Phase 1: Without READ_QUERY_HISTORY — /admin/performance/query-history should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/performance/query-history");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Phase 2: Grant READ_QUERY_HISTORY — /admin/performance/query-history should be accessible
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, [
        Permission.READ_QUERY_HISTORY,
      ]);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/performance/query-history");
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain("/admin/performance/query-history");
      await expect(
        page.getByLabel("admin-page-title").getByText("Query History")
      ).toBeVisible({ timeout: 10000 });

      // Phase 3: Revoke READ_QUERY_HISTORY — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/performance/query-history");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      // Cleanup: delete the chat session
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const cleanupClient = new OnyxApiClient(page.request);
      await cleanupClient.deleteChatSession(chatSessionId);
    }
  });
});

test.describe("Permission gating — CREATE_USER_API_KEYS", () => {
  test("Access Tokens section and New Access Token button are gated behind CREATE_USER_API_KEYS", async ({
    page,
    adminClient,
    testUserContext,
  }) => {
    const registryResponse = await page.request.get(
      "/api/manage/admin/permissions/registry"
    );
    test.skip(
      registryResponse.status() === 404,
      "Permission registry unavailable (CE environment)"
    );

    const { groupId, email, password } = testUserContext;
    let createdPatId: number | undefined;

    try {
      // Phase 1: Without permission and no tokens — section should be hidden entirely
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/app/settings/accounts-access");
      await page.waitForLoadState("networkidle");

      await expect(
        page.getByText("Access Tokens", { exact: true })
      ).not.toBeVisible();
      await expect(
        page.getByRole("button", { name: "New Access Token" })
      ).not.toBeVisible();

      // Phase 2: Grant CREATE_USER_API_KEYS — section visible, button enabled
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, [
        Permission.CREATE_USER_API_KEYS,
      ]);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/app/settings/accounts-access");
      await page.waitForLoadState("networkidle");

      await expect(
        page.getByText("Access Tokens", { exact: true })
      ).toBeVisible({ timeout: 10000 });

      const newTokenButton = page.getByRole("button", {
        name: "New Access Token",
      });
      await expect(newTokenButton).toBeVisible({ timeout: 10000 });
      await expect(newTokenButton).toBeEnabled();

      // Create a PAT via API so Phase 3 can test "token exists but no permission"
      const createResponse = await page.request.post("/api/user/pats", {
        data: {
          name: `E2E PAT ${Date.now()}`,
          expiration_days: 30,
        },
      });
      expect(createResponse.ok()).toBeTruthy();
      const patData = await createResponse.json();
      createdPatId = patData.id;

      // Phase 3: Revoke permission — section stays (token exists) but button disabled
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/app/settings/accounts-access");
      await page.waitForLoadState("networkidle");

      await expect(
        page.getByText("Access Tokens", { exact: true })
      ).toBeVisible({ timeout: 10000 });

      await expect(newTokenButton).toBeVisible({ timeout: 10000 });
      await expect(newTokenButton).toBeDisabled();
    } finally {
      // Cleanup: delete the PAT (only requires BASIC_ACCESS)
      if (createdPatId !== undefined) {
        await page.context().clearCookies();
        await apiLogin(page, email, password);
        await page.request
          .delete(`/api/user/pats/${createdPatId}`)
          .catch(() => {});
      }
    }
  });
});

test.describe("Permission gating — MANAGE_USER_GROUPS", () => {
  test("Admin panel /admin/groups and /admin/groups/create are gated behind MANAGE_USER_GROUPS, with implied READ_CONNECTORS, READ_DOCUMENT_SETS, and READ_AGENTS", async ({
    page,
    adminClient,
    testUserContext,
  }) => {
    const registryResponse = await page.request.get(
      "/api/manage/admin/permissions/registry"
    );
    test.skip(
      registryResponse.status() === 404,
      "Permission registry unavailable (CE environment)"
    );

    const { groupId, email, password } = testUserContext;

    // Admin creates test data for implied permission verification
    const connectorName = `E2E ManageGroups Connector ${Date.now()}`;
    const ccPairId = await adminClient.createFileConnector(
      connectorName,
      "public"
    );

    const agentName = `E2E ManageGroups Agent ${Date.now()}`;
    const agentId = await adminClient.createAgent(agentName, "Test agent");

    const docSetName = `E2E ManageGroups DocSet ${Date.now()}`;
    const docSetId = await adminClient.createDocumentSet(docSetName, [
      ccPairId,
    ]);

    // Extra user group so the groups list has a visible custom group card
    const extraGroupName = `E2E ManageGroups Group ${Date.now()}`;
    const extraGroupId = await adminClient.createUserGroup(extraGroupName, [
      testUserContext.userId,
    ]);

    try {
      // Phase 1: Without MANAGE_USER_GROUPS — /admin/groups should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/groups");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Also verify /admin/groups/create redirects
      await page.goto("/admin/groups/create");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Phase 2: Grant MANAGE_USER_GROUPS — pages should be accessible
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, [
        Permission.MANAGE_USER_GROUPS,
      ]);

      await page.context().clearCookies();
      await apiLogin(page, email, password);

      // Verify groups list page
      await page.goto("/admin/groups");
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain("/admin/groups");
      await expect(page.getByTestId("groups-page-heading")).toBeVisible({
        timeout: 10000,
      });
      await expect(
        page.getByRole("button", { name: "New Group" })
      ).toBeVisible();
      await expect(page.getByText(extraGroupName)).toBeVisible();

      // Navigate to create page to verify implied permissions
      await page.goto("/admin/groups/create");
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain("/admin/groups/create");
      await expect(
        page.getByLabel("admin-page-title").getByText("Create Group")
      ).toBeVisible({ timeout: 10000 });

      // Open connectors & document sets popover and verify items (proves READ_CONNECTORS + READ_DOCUMENT_SETS)
      const connectorDocSetInput = page.getByPlaceholder(
        "Add connectors, document sets"
      );
      await expect(connectorDocSetInput).toBeVisible({ timeout: 10000 });
      await connectorDocSetInput.click();
      await expect(page.getByText(connectorName).first()).toBeVisible({
        timeout: 10000,
      });
      await expect(page.getByText(docSetName).first()).toBeVisible({
        timeout: 10000,
      });

      // Dismiss the connectors popover by pressing Escape before opening agents
      await page.keyboard.press("Escape");

      // Open agents popover and verify item (proves READ_AGENTS)
      const agentsInput = page.getByPlaceholder("Add agents");
      await expect(agentsInput).toBeVisible({ timeout: 10000 });
      await agentsInput.click();
      await expect(page.getByText(agentName).first()).toBeVisible({
        timeout: 10000,
      });

      // Phase 3: Revoke MANAGE_USER_GROUPS — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto("/admin/groups");
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      // Cleanup: delete resources (doc set before connector since it references it)
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const cleanupClient = new OnyxApiClient(page.request);
      await cleanupClient.deleteDocumentSet(docSetId);
      await cleanupClient.deleteCCPair(ccPairId);
      await cleanupClient.deleteAgent(agentId);
      await cleanupClient.deleteUserGroup(extraGroupId);
    }
  });
});
