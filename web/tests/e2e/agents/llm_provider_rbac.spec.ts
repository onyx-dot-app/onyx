import { test } from "@playwright/test";
import { loginAsRandomUser, loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AgentEditorPage } from "@tests/e2e/pages/AgentEditorPage";

/**
 * This test verifies that LLM Provider RBAC works correctly in the assistant editor.
 *
 * Test scenario:
 * 1. Create a restricted LLM provider (not public, assigned to specific group)
 * 2. Create a user who doesn't have access to the restricted provider
 * 3. Navigate to assistant creation page
 * 4. Verify the restricted provider doesn't appear in the LLM selector
 */

test("Restricted LLM Provider should not appear for unauthorized users", async ({
  page,
}) => {
  await page.context().clearCookies();

  // Step 1: Login as admin to create test fixtures
  await loginAs(page, "admin");
  await page.waitForLoadState("networkidle");

  // Step 2: Create a user group that will have access to the restricted provider
  const restrictedGroupName = `Restricted Group ${Date.now()}`;
  let groupId: number | null = null;
  let providerId: number | null = null;

  const client = new OnyxApiClient(page.request);

  try {
    groupId = await client.createUserGroup(restrictedGroupName);
    console.log(`Created user group with ID: ${groupId}`);

    // Step 3: Create a restricted LLM provider assigned to that group
    const restrictedProviderName = `Restricted Provider ${Date.now()}`;
    providerId = await client.createRestrictedProvider(
      restrictedProviderName,
      groupId
    );
    console.log(
      `Created restricted provider "${restrictedProviderName}" with ID: ${providerId}`
    );

    // Step 4: Logout and login as a random user (who won't be in the restricted group)
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    const agentEditor = new AgentEditorPage(page);
    await agentEditor.goto();
    await agentEditor.expectDefaultModelOptions({
      visible: [/Default|GPT|Claude/i],
      hidden: [restrictedProviderName],
    });

    console.log(
      `✓ Verified restricted provider "${restrictedProviderName}" does not appear for unauthorized user`
    );
  } finally {
    // Cleanup: Login as admin again to delete test fixtures
    await page.context().clearCookies();
    await loginAs(page, "admin");
    await page.waitForLoadState("networkidle");

    if (providerId) {
      await client.deleteProvider(providerId);
      console.log(`Deleted provider with ID: ${providerId}`);
    }

    if (groupId) {
      await client.deleteUserGroup(groupId);
      console.log(`Deleted user group with ID: ${groupId}`);
    }
  }
});

test("Agent-restricted provider appears in its default model selector", async ({
  page,
}) => {
  await page.context().clearCookies();
  await loginAs(page, "admin");

  const client = new OnyxApiClient(page.request);
  const suffix = Date.now();
  let agentId: number | null = null;
  let providerId: number | null = null;

  try {
    agentId = await client.createAgent(`Restricted Model Agent ${suffix}`);
    const providerName = `Agent Provider ${suffix}`;
    providerId = await client.createAgentRestrictedProvider(providerName, [
      agentId,
    ]);

    const agentEditor = new AgentEditorPage(page);
    await agentEditor.gotoEdit(agentId);
    await agentEditor.expectDefaultModelOptions({
      visible: [providerName],
    });
  } finally {
    if (providerId) {
      await client.deleteProvider(providerId);
    }
    if (agentId) {
      await client.deleteAgent(agentId);
    }
  }
});

test("Default Model selector shows available models", async ({ page }) => {
  await page.context().clearCookies();
  await loginAsRandomUser(page);

  const agentEditor = new AgentEditorPage(page);
  await agentEditor.goto();
  await agentEditor.expectDefaultModelOptions({
    visible: [/default/i],
  });
});
