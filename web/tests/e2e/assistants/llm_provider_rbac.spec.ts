import { test, expect } from "@chromatic-com/playwright";
import { Page } from "@playwright/test";
import { loginAsRandomUser, loginAs } from "../utils/auth";
import { OnyxApiClient } from "../utils/onyxApiClient";

/**
 * This test verifies that LLM Provider RBAC works correctly in the assistant editor.
 *
 * Test scenario:
 * 1. Create a restricted LLM provider (not public, assigned to specific group)
 * 2. Create a user who doesn't have access to the restricted provider
 * 3. Navigate to assistant creation page
 * 4. Verify the restricted provider doesn't appear in the LLM selector
 */

const getDefaultModelSelector = (page: Page) =>
  page
    .locator(
      'button:has-text("User Default"), button:has-text("System Default")'
    )
    .first();

const getLLMProviderOptions = async (page: Page) => {
  // Click the selector to open the dropdown
  await getDefaultModelSelector(page).click();

  // Wait for the dropdown to be visible
  await page.waitForSelector('[role="option"]', { state: "visible" });

  // Get all visible options
  const options = await page.locator('[role="option"]').allTextContents();

  // Close the dropdown by clicking elsewhere
  await page.keyboard.press("Escape");

  return options;
};

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

  const client = new OnyxApiClient(page);

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

    // Step 5: Navigate to the assistant creation page
    await page.goto("/chat/agents/create");
    await page.waitForLoadState("networkidle");

    // Step 6: Scroll to the Default Model section
    const defaultModelSection = page.locator("text=Default Model").first();
    await defaultModelSection.scrollIntoViewIfNeeded();

    // Step 7: Get all available LLM provider options
    const llmOptions = await getLLMProviderOptions(page);

    // Step 8: Verify that we have some options (at least the default provider)
    expect(llmOptions.length).toBeGreaterThan(0);

    // Step 9: Verify the restricted provider does NOT appear
    const hasRestrictedProvider = llmOptions.some((option) =>
      option.includes(restrictedProviderName)
    );
    expect(hasRestrictedProvider).toBe(false);

    // Step 10: Verify that default/public providers DO appear
    const hasDefaultOption = llmOptions.some(
      (option) =>
        option.includes("Default") ||
        option.includes("GPT") ||
        option.includes("Claude")
    );
    expect(hasDefaultOption).toBe(true);

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

test("Default Model selector shows available models", async ({ page }) => {
  await page.context().clearCookies();
  await loginAsRandomUser(page);

  // Navigate to the assistant creation page
  await page.goto("/chat/agents/create");
  await page.waitForLoadState("networkidle");

  // Scroll to the Default Model section
  const defaultModelSection = page.locator("text=Default Model").first();
  await defaultModelSection.scrollIntoViewIfNeeded();

  // Open the model selector
  await getDefaultModelSelector(page).click();
  await page.waitForSelector('[role="option"]', { state: "visible" });

  // Get all options
  const options = await page.locator('[role="option"]').allTextContents();

  // Close dropdown
  await page.keyboard.press("Escape");

  // Verify we have at least the default option
  expect(options.length).toBeGreaterThan(0);

  // Verify the default/system default option exists
  const hasDefaultOption = options.some((option) =>
    option.toLowerCase().includes("default")
  );
  expect(hasDefaultOption).toBeTruthy();
});
