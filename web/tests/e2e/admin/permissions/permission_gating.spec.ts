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
