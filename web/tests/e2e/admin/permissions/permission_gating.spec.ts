import { test, expect } from "./fixtures";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Permission } from "@/lib/types";
import { apiLogin, loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminAgentsPage } from "@tests/e2e/pages/AdminAgentsPage";

/** After a timeout the context is closed, so an unguarded cleanup throws and
 *  replaces the real error. */
async function cleanup(fn: () => Promise<void>): Promise<void> {
  try {
    await fn();
  } catch {
    // real failure already recorded
  }
}

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

    // The disabled button is only a hint — assert the API itself rejects creation without
    // ADD_AGENTS, so a hidden control over an open endpoint can't be a false green.
    const createResp = await page.request.post("/api/persona", {
      data: {
        name: `perm-test-agent-${Date.now()}`,
        description: "",
        system_prompt: "",
        task_prompt: "",
        datetime_aware: false,
        document_set_ids: [],
        is_public: false,
        groups: [],
        tool_ids: [],
      },
    });
    expect(createResp.status()).toBe(403);
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

    const agentName = `E2E Manage Agent ${Date.now()}`;
    const agentId = await adminClient.createAgent(agentName, "Test agent");

    try {
      // Phase 1: Without MANAGE_AGENTS — /admin/agents should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto(ADMIN_ROUTES.AGENTS.path);
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
      await page.goto(ADMIN_ROUTES.AGENTS.path);
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain(ADMIN_ROUTES.AGENTS.path);
      await expect(page.getByRole("link", { name: "New Agent" })).toBeVisible({
        timeout: 10000,
      });
      await expect(page.getByText(agentName)).toBeVisible();

      // Row controls come from the server-stamped affordance map; a wrong projection
      // empties the overflow menu instead of erroring, so assert the items.
      const agentsPage = new AdminAgentsPage(page);
      await expect(agentsPage.editButton(agentId)).toBeVisible({
        timeout: 10000,
      });
      await agentsPage.expectActions(agentId, {
        visible: ["Share", "Stats", "Delete"],
        hidden: [],
      });

      // Phase 3: Revoke MANAGE_AGENTS — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto(ADMIN_ROUTES.AGENTS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      await cleanup(async () => {
        await page.context().clearCookies();
        await loginAs(page, "admin");
        const cleanupClient = new OnyxApiClient(page.request);
        await cleanupClient.deleteAgent(agentId);
      });
    }
  });
});

test.describe("Permission gating — MANAGE_LLMS", () => {
  test("Admin panel and /admin/language-models are gated behind MANAGE_LLMS", async ({
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

    const providerName = `E2E Manage LLM ${Date.now()}`;
    const providerId = await adminClient.createProvider(providerName);
    // The Cost Overrides panel sits on this page but reads its own endpoint, so
    // seed a row the holder must be able to see.
    const overrideModel = await adminClient.upsertCostOverride(
      `e2e-manage-llm-${Date.now()}`
    );

    try {
      // Phase 1: Without MANAGE_LLMS — the page should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto(ADMIN_ROUTES.LLM_MODELS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Phase 2: Grant MANAGE_LLMS — the page should be accessible
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, [
        Permission.MANAGE_LLMS,
      ]);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto(ADMIN_ROUTES.LLM_MODELS.path);
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain(ADMIN_ROUTES.LLM_MODELS.path);
      await expect(
        page.getByLabel("admin-page-title").getByText("Language Models")
      ).toBeVisible({
        timeout: 10000,
      });
      await expect(page.getByText(providerName)).toBeVisible();

      // Cost overrides are gated separately from the page, so reaching the page
      // is not evidence the panel loaded — assert the row, not just the heading.
      await expect(page.getByText(overrideModel)).toBeVisible({
        timeout: 10000,
      });
      await expect(
        page.getByText("Failed to load cost overrides.")
      ).toBeHidden();

      // Phase 3: Revoke MANAGE_LLMS — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto(ADMIN_ROUTES.LLM_MODELS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      await cleanup(async () => {
        await page.context().clearCookies();
        await loginAs(page, "admin");
        const cleanupClient = new OnyxApiClient(page.request);
        await cleanupClient.deleteProvider(providerId);
        await cleanupClient.deleteCostOverride(overrideModel);
      });
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

    const connectorName = `E2E Manage Connector ${Date.now()}`;
    const ccPairId = await adminClient.createFileConnector(connectorName);

    try {
      // Phase 1: Without MANAGE_CONNECTORS — /admin/indexing/status should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto(ADMIN_ROUTES.INDEXING_STATUS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Also verify /admin/add-connector redirects
      await page.goto(ADMIN_ROUTES.ADD_CONNECTOR.path);
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
      await page.goto(ADMIN_ROUTES.INDEXING_STATUS.path);
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain(ADMIN_ROUTES.INDEXING_STATUS.path);
      await expect(
        page.getByLabel("admin-page-title").getByText("Existing Connectors")
      ).toBeVisible({ timeout: 10000 });
      await expect(page.getByRole("table")).toBeVisible();

      // Also verify /admin/add-connector is accessible
      await page.goto(ADMIN_ROUTES.ADD_CONNECTOR.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain(ADMIN_ROUTES.ADD_CONNECTOR.path);
      await expect(
        page.getByLabel("admin-page-title").getByText("Add Connector")
      ).toBeVisible({ timeout: 10000 });

      // Access type and groups live on the wizard's second step, so reaching
      // /admin/add-connector says nothing about them. `web` has no credential
      // template, so the wizard skips straight there.
      await page.goto("/admin/connectors/web");
      await page.waitForLoadState("networkidle");
      await expect(page.getByText("Document Access")).toBeVisible({
        timeout: 10000,
      });

      // a global holder defaults to public, which has no groups to scope
      // must be the picker, not "assigned to group X" — the old code auto-assigned
      await page.getByText("Public", { exact: true }).first().click();
      await page.getByText("Private", { exact: true }).first().click();
      await expect(
        page.getByText("Assign group access for this Connector")
      ).toBeVisible({ timeout: 10000 });

      // Drive's credential form used to render an empty fragment for non-admins
      // — a blank modal, no error, no network call.
      await page.goto("/admin/connectors/google-drive");
      await page.waitForLoadState("networkidle");
      await page.getByRole("button", { name: "Create New" }).click();
      await expect(
        page.getByText("Authenticate with Google Drive")
      ).toBeVisible({ timeout: 10000 });

      // Phase 3: Revoke MANAGE_CONNECTORS — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto(ADMIN_ROUTES.INDEXING_STATUS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      await cleanup(async () => {
        await page.context().clearCookies();
        await loginAs(page, "admin");
        const cleanupClient = new OnyxApiClient(page.request);
        await cleanupClient.deleteCCPair(ccPairId);
      });
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

    const connectorName = `E2E DocSet Connector ${Date.now()}`;
    const ccPairId = await adminClient.createFileConnector(
      connectorName,
      "public"
    );
    // Private and group-less is what the curator-era filter binned. A public
    // connector stayed visible either way, so it couldn't detect filtering.
    const privateConnectorName = `E2E DocSet Private ${Date.now()}`;
    const privateCcPairId = await adminClient.createFileConnector(
      privateConnectorName,
      "private"
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
      await page.goto(ADMIN_ROUTES.DOCUMENT_SETS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Also verify /admin/documents/sets/new redirects
      await page.goto(`${ADMIN_ROUTES.DOCUMENT_SETS.path}/new`);
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
      await page.goto(ADMIN_ROUTES.DOCUMENT_SETS.path);
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain(ADMIN_ROUTES.DOCUMENT_SETS.path);
      await expect(
        page.getByLabel("admin-page-title").getByText("Document Sets")
      ).toBeVisible({ timeout: 10000 });
      await expect(page.getByText("New Document Set")).toBeVisible();

      // Navigate to creation page to verify implied READ_CONNECTORS
      await page.goto(`${ADMIN_ROUTES.DOCUMENT_SETS.path}/new`);
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain(`${ADMIN_ROUTES.DOCUMENT_SETS.path}/new`);
      await expect(
        page.getByLabel("admin-page-title").getByText("New Document Set")
      ).toBeVisible({ timeout: 10000 });

      // Open the connector dropdown
      const connectorSearchInput = page.getByTestId("connector-search-input");
      await expect(connectorSearchInput).toBeVisible({ timeout: 10000 });
      await connectorSearchInput.click();

      // Connector visible proves implied READ_CONNECTORS
      await expect(page.getByText(connectorName)).toBeVisible({
        timeout: 10000,
      });

      // A global holder is org-wide, so this is selectable, not filtered out.
      await expect(page.getByText(privateConnectorName)).toBeVisible({
        timeout: 10000,
      });
      await expect(
        page.getByText("Connectors not available", { exact: false })
      ).toBeHidden();

      // Group selector loaded proves implied READ_USER_GROUPS
      await expect(
        page.getByText("Assign group access for this document set")
      ).toBeVisible({ timeout: 10000 });
      await expect(
        page.getByText(
          "Failed to load assign group access for this document set"
        )
      ).not.toBeVisible();

      // Rendered only for a holder of this permission — its presence is the
      // assertion that MANAGE_DOCUMENT_SETS is honoured, not just admin.
      // the input is a 1x1 hidden box; the label beside it is what's clickable
      const publicToggle = page.locator("#checkbox-is_public");
      await expect(publicToggle).toBeAttached({ timeout: 10000 });
      const publicToggleLabel = page
        .getByText("Make this Document Set Public?", { exact: false })
        .first();
      await expect(publicToggleLabel).toBeVisible({ timeout: 10000 });

      // Document sets default to public, and a public set has no groups to
      // scope, so the picker is disabled until this is unticked.
      await publicToggleLabel.click();

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
      await page.goto(ADMIN_ROUTES.DOCUMENT_SETS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      await cleanup(async () => {
        await page.context().clearCookies();
        await loginAs(page, "admin");
        const cleanupClient = new OnyxApiClient(page.request);
        await cleanupClient.deleteCCPair(ccPairId);
        await cleanupClient.deleteCCPair(privateCcPairId);
        await cleanupClient.deleteUserGroup(extraGroupId);
      });
    }
  });
});

test.describe("Permission gating — MANAGE_ACTIONS", () => {
  test("Admin panel /admin/mcp-actions and /admin/openapi-actions are gated behind MANAGE_ACTIONS", async ({
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

    const toolName = `E2E Manage Tool ${Date.now()}`;
    const toolId = await adminClient.createCustomTool(toolName);

    const mcpName = `E2E Manage MCP ${Date.now()}`;
    const mcpServerId = await adminClient.createMcpServer(mcpName);

    try {
      // Phase 1: Without MANAGE_ACTIONS — both pages should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto(ADMIN_ROUTES.OPENAPI_ACTIONS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      await page.goto(ADMIN_ROUTES.MCP_ACTIONS.path);
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
      await page.goto(ADMIN_ROUTES.OPENAPI_ACTIONS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain(ADMIN_ROUTES.OPENAPI_ACTIONS.path);
      await expect(
        page.getByLabel("admin-page-title").getByText("OpenAPI Actions")
      ).toBeVisible({ timeout: 10000 });
      await expect(
        page.getByLabel(`${toolName} OpenAPI action card`)
      ).toBeVisible({ timeout: 10000 });

      // Verify MCP Actions page and created server visibility
      await page.goto(ADMIN_ROUTES.MCP_ACTIONS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain(ADMIN_ROUTES.MCP_ACTIONS.path);
      await expect(
        page.getByLabel("admin-page-title").getByText("MCP Actions")
      ).toBeVisible({ timeout: 10000 });
      await expect(page.getByLabel(`${mcpName} MCP server card`)).toBeVisible({
        timeout: 10000,
      });

      // The Add-MCP-Server modal hosts the shared group selector, the same
      // component that hid its Public toggle from non-admins on other forms.
      await page.getByRole("button", { name: "Add MCP Server" }).click();
      await expect(page.getByText("MCP Server URL")).toBeVisible({
        timeout: 10000,
      });

      // Rendered only for a holder of this permission.
      const mcpPublicToggle = page.locator("#checkbox-is_public");
      await expect(mcpPublicToggle).toBeAttached({ timeout: 10000 });
      const mcpPublicToggleLabel = page
        .getByText("Make this MCP Server Public?", { exact: false })
        .first();
      await expect(mcpPublicToggleLabel).toBeVisible({ timeout: 10000 });

      // MCP servers default to public, so the picker is disabled until unticked.
      await mcpPublicToggleLabel.click();
      await expect(
        page.getByText("Assign group access for this MCP server")
      ).toBeVisible({ timeout: 10000 });
      await expect(page.getByTestId("groups-search-input")).toBeVisible({
        timeout: 10000,
      });

      // Phase 3: Revoke MANAGE_ACTIONS — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto(ADMIN_ROUTES.OPENAPI_ACTIONS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      await page.goto(ADMIN_ROUTES.MCP_ACTIONS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      await cleanup(async () => {
        await page.context().clearCookies();
        await loginAs(page, "admin");
        const cleanupClient = new OnyxApiClient(page.request);
        await cleanupClient.deleteCustomTool(toolId);
        await cleanupClient.deleteMcpServer(mcpServerId);
      });
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

    const accountName = `E2E Service Account ${Date.now()}`;
    const apiKeyId = await adminClient.createServiceAccount(accountName);

    // Admin creates a second user group (so the groups dropdown has content to render)
    const extraGroupName = `E2E SvcAcct Group ${Date.now()}`;
    const extraGroupId = await adminClient.createUserGroup(extraGroupName);

    try {
      // Phase 1: Without MANAGE_SERVICE_ACCOUNT_API_KEYS — /admin/service-accounts should redirect to /app
      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto(ADMIN_ROUTES.API_KEYS.path);
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
      await page.goto(ADMIN_ROUTES.API_KEYS.path);
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain(ADMIN_ROUTES.API_KEYS.path);
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

      // Defaults too (include_default) — hiding them would make those levels
      // ungrantable to a key.
      await expect(
        page.getByText("Admin", { exact: true }).first()
      ).toBeVisible({
        timeout: 10000,
      });
      await expect(
        page.getByText("Basic", { exact: true }).first()
      ).toBeVisible({
        timeout: 10000,
      });

      // Phase 3: Revoke MANAGE_SERVICE_ACCOUNT_API_KEYS — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto(ADMIN_ROUTES.API_KEYS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      await cleanup(async () => {
        await page.context().clearCookies();
        await loginAs(page, "admin");
        const cleanupClient = new OnyxApiClient(page.request);
        await cleanupClient.deleteServiceAccount(apiKeyId);
        await cleanupClient.deleteUserGroup(extraGroupId);
      });
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
      await page.goto(ADMIN_ROUTES.SLACK_BOTS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      await page.goto(ADMIN_ROUTES.DISCORD_BOTS.path);
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
      await page.goto(ADMIN_ROUTES.SLACK_BOTS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain(ADMIN_ROUTES.SLACK_BOTS.path);
      await expect(
        page.getByLabel("admin-page-title").getByText("Slack Integration")
      ).toBeVisible({ timeout: 10000 });
      // href Buttons render as links, not buttons
      await expect(
        page.getByRole("link", { name: "New Slack Bot" })
      ).toBeVisible();

      // Verify Discord Integration page
      await page.goto(ADMIN_ROUTES.DISCORD_BOTS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain(ADMIN_ROUTES.DISCORD_BOTS.path);
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
      await page.goto(ADMIN_ROUTES.SLACK_BOTS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      await page.goto(ADMIN_ROUTES.DISCORD_BOTS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      await cleanup(async () => {
        await page.context().clearCookies();
        await loginAs(page, "admin");
        const cleanupClient = new OnyxApiClient(page.request);
        await cleanupClient.deleteDiscordGuild(guild.id);
      });
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
      await page.goto(ADMIN_ROUTES.QUERY_HISTORY.path);
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
      await page.goto(ADMIN_ROUTES.QUERY_HISTORY.path);
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain(ADMIN_ROUTES.QUERY_HISTORY.path);
      await expect(
        page.getByLabel("admin-page-title").getByText("Query History")
      ).toBeVisible({ timeout: 10000 });

      // The table fetches separately, so reaching the page isn't evidence it loaded.
      await expect(page.getByText("Error fetching query history")).toBeHidden();

      // Phase 3: Revoke READ_QUERY_HISTORY — should redirect again
      await page.context().clearCookies();
      await loginAs(page, "admin");
      await adminClient.setUserGroupPermissions(groupId, []);

      await page.context().clearCookies();
      await apiLogin(page, email, password);
      await page.goto(ADMIN_ROUTES.QUERY_HISTORY.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      await cleanup(async () => {
        await page.context().clearCookies();
        await loginAs(page, "admin");
        const cleanupClient = new OnyxApiClient(page.request);
        await cleanupClient.deleteChatSession(chatSessionId);
      });
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
      await cleanup(async () => {
        // Delete the PAT (only requires BASIC_ACCESS)
        if (createdPatId !== undefined) {
          await page.context().clearCookies();
          await apiLogin(page, email, password);
          await page.request
            .delete(`/api/user/pats/${createdPatId}`)
            .catch(() => {});
        }
      });
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
      await page.goto(ADMIN_ROUTES.GROUPS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");

      // Also verify /admin/groups/create redirects
      await page.goto(`${ADMIN_ROUTES.GROUPS.path}/create`);
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
      await page.goto(ADMIN_ROUTES.GROUPS.path);
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain(ADMIN_ROUTES.GROUPS.path);
      await expect(page.getByTestId("groups-page-heading")).toBeVisible({
        timeout: 10000,
      });
      await expect(
        page.getByRole("button", { name: "New Group" })
      ).toBeVisible();
      await expect(page.getByText(extraGroupName)).toBeVisible();

      // Navigate to create page to verify implied permissions
      await page.goto(`${ADMIN_ROUTES.GROUPS.path}/create`);
      await page.waitForLoadState("networkidle");

      expect(page.url()).toContain(`${ADMIN_ROUTES.GROUPS.path}/create`);
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

      // Dismiss the connectors popover before opening agents
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
      await page.goto(ADMIN_ROUTES.GROUPS.path);
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/app");
    } finally {
      await cleanup(async () => {
        // Delete doc set before connector since it references it
        await page.context().clearCookies();
        await loginAs(page, "admin");
        const cleanupClient = new OnyxApiClient(page.request);
        await cleanupClient.deleteDocumentSet(docSetId);
        await cleanupClient.deleteCCPair(ccPairId);
        await cleanupClient.deleteAgent(agentId);
        await cleanupClient.deleteUserGroup(extraGroupId);
      });
    }
  });
});
