import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs, loginAsRandomUser, apiLogin } from "./utils/auth";
import { OnyxApiClient } from "./utils/onyxApiClient";
import { expectElementScreenshot } from "./utils/visualRegression";

/**
 * Onboarding Flow E2E Tests
 *
 * Tests the 4 main user scenarios:
 * 1. Admin WITHOUT LLM providers -> Full onboarding, chat disabled
 * 2. Admin WITH LLM providers -> No full onboarding, chat enabled
 * 3. Non-admin WITHOUT LLM providers -> NonAdminStep name prompt, chat disabled
 * 4. Non-admin WITH LLM providers -> NonAdminStep name prompt, chat enabled
 *
 * Marked @exclusive because scenarios 1 & 3 delete all LLM providers.
 */

async function deleteAllProviders(client: OnyxApiClient): Promise<void> {
  const providers = await client.listLlmProviders();
  for (const provider of providers) {
    try {
      await client.deleteProvider(provider.id);
    } catch (error) {
      console.warn(
        `Failed to delete provider ${provider.id}: ${String(error)}`
      );
    }
  }
}

async function createFreshAdmin(
  page: Page
): Promise<{ email: string; password: string }> {
  // First, log in as the existing admin so we can promote the new user
  await page.context().clearCookies();
  const { email, password } = await loginAsRandomUser(page);

  // Now promote the new user to admin via the existing admin
  await page.context().clearCookies();
  await loginAs(page, "admin");
  const adminClient = new OnyxApiClient(page.request);
  await adminClient.setUserRole(email, "admin");

  // Log back in as the new admin
  await page.context().clearCookies();
  await apiLogin(page, email, password);

  return { email, password };
}

async function createFreshUser(
  page: Page
): Promise<{ email: string; password: string }> {
  await page.context().clearCookies();
  return await loginAsRandomUser(page);
}

test.describe("Onboarding Flow @exclusive", () => {
  test.describe("Scenario 1: Admin WITHOUT LLM providers", () => {
    test.beforeEach(async ({ page }) => {
      // Delete all providers first (as existing admin)
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await deleteAllProviders(adminClient);

      // Create a fresh admin user (no chat history)
      await createFreshAdmin(page);
    });

    test.afterEach(async ({ page }) => {
      // Restore providers
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await adminClient.ensurePublicProvider();
    });

    test("shows full onboarding flow with Welcome step", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const onboardingFlow = page.locator('[data-label="onboarding-flow"]');
      await expect(onboardingFlow).toBeVisible({ timeout: 15000 });

      const header = page.locator('[data-label="onboarding-header"]');
      await expect(header).toBeVisible();
      await expect(
        header.getByRole("button", { name: "Let's Go" })
      ).toBeVisible();

      await expectElementScreenshot(header, {
        name: "onboarding-welcome-step",
      });
    });

    test("chat input bar is disabled during onboarding", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // Wait for the onboarding to appear
      await expect(page.locator('[data-label="onboarding-flow"]')).toBeVisible({
        timeout: 15000,
      });

      const chatInput = page.locator("#onyx-chat-input");
      await expect(chatInput).toHaveAttribute("aria-disabled", "true");

      await expectElementScreenshot(chatInput, {
        name: "onboarding-chat-disabled",
      });
    });

    test("can progress through onboarding steps", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // Welcome step
      const header = page.locator('[data-label="onboarding-header"]');
      await expect(header).toBeVisible({ timeout: 15000 });

      // Click "Let's Go" to advance to Name step
      await header.getByRole("button", { name: "Let's Go" }).click();

      // Name step
      const nameStep = page.locator('[data-label="onboarding-name-step"]');
      await expect(nameStep).toBeVisible({ timeout: 10000 });

      // Enter a name and click Next
      await nameStep.getByPlaceholder("Your name").fill("Test Admin");

      await expectElementScreenshot(nameStep, {
        name: "onboarding-name-step",
      });

      // Wait for the Next button to be enabled (debounce)
      const nextButton = header.getByRole("button", { name: "Next" });
      await expect(nextButton).toBeEnabled({ timeout: 10000 });
      await nextButton.click();

      // LLM setup step
      const llmStep = page.locator('[data-label="onboarding-llm-step"]');
      await expect(llmStep).toBeVisible({ timeout: 10000 });

      await expectElementScreenshot(llmStep, {
        name: "onboarding-llm-step",
      });
    });
  });

  test.describe("Scenario 2: Admin WITH LLM providers", () => {
    test.beforeEach(async ({ page }) => {
      // Ensure provider exists
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await adminClient.ensurePublicProvider();

      // Create a fresh admin user
      await createFreshAdmin(page);
    });

    test("does not show full onboarding flow", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // The full onboarding flow should NOT appear
      await expect(
        page.locator('[data-label="onboarding-flow"]')
      ).not.toBeVisible({ timeout: 5000 });
    });

    test("shows name prompt (NonAdminStep) when name not set", async ({
      page,
    }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // The NonAdminStep name prompt should appear for admins without a name
      const namePrompt = page.locator('[data-label="non-admin-name-prompt"]');
      await expect(namePrompt).toBeVisible({ timeout: 15000 });
      await expect(
        namePrompt.getByRole("button", { name: "Save" })
      ).toBeVisible();

      await expectElementScreenshot(namePrompt, {
        name: "onboarding-admin-name-prompt",
      });
    });

    test("chat input bar is enabled", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // Wait for page to settle
      await expect(page.locator("#onyx-chat-input")).toBeVisible({
        timeout: 15000,
      });

      const chatInput = page.locator("#onyx-chat-input");
      await expect(chatInput).not.toHaveAttribute("aria-disabled", "true");
    });
  });

  test.describe("Scenario 3: Non-admin WITHOUT LLM providers", () => {
    test.beforeEach(async ({ page }) => {
      // Delete all providers (as existing admin)
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await deleteAllProviders(adminClient);

      // Create a fresh non-admin user
      await createFreshUser(page);
    });

    test.afterEach(async ({ page }) => {
      // Restore providers
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await adminClient.ensurePublicProvider();
    });

    test("shows NonAdminStep name prompt", async ({ page }) => {
      // loginAsRandomUser already navigates to /app
      const namePrompt = page.locator('[data-label="non-admin-name-prompt"]');
      await expect(namePrompt).toBeVisible({ timeout: 15000 });
      await expect(
        namePrompt.getByRole("button", { name: "Save" })
      ).toBeVisible();

      await expectElementScreenshot(namePrompt, {
        name: "onboarding-nonadmin-name-prompt",
      });
    });

    test("does NOT show full onboarding flow", async ({ page }) => {
      // The full admin onboarding should not appear
      await expect(
        page.locator('[data-label="onboarding-flow"]')
      ).not.toBeVisible({ timeout: 5000 });
      await expect(
        page.locator('[data-label="onboarding-llm-step"]')
      ).not.toBeVisible();
    });

    test("chat input bar is disabled", async ({ page }) => {
      await expect(page.locator("#onyx-chat-input")).toBeVisible({
        timeout: 15000,
      });

      const chatInput = page.locator("#onyx-chat-input");
      await expect(chatInput).toHaveAttribute("aria-disabled", "true");
    });

    test("can save name and see confirmation", async ({ page }) => {
      const namePrompt = page.locator('[data-label="non-admin-name-prompt"]');
      await expect(namePrompt).toBeVisible({ timeout: 15000 });

      await namePrompt.getByPlaceholder("Your name").fill("Test User");
      await namePrompt.getByRole("button", { name: "Save" }).click();

      const confirmation = page.locator(
        '[data-label="non-admin-confirmation"]'
      );
      await expect(confirmation).toBeVisible({ timeout: 10000 });

      await expectElementScreenshot(confirmation, {
        name: "onboarding-nonadmin-confirmation",
      });
    });
  });

  test.describe("Scenario 4: Non-admin WITH LLM providers", () => {
    test.beforeEach(async ({ page }) => {
      // Ensure provider exists
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await adminClient.ensurePublicProvider();

      // Create a fresh non-admin user
      await createFreshUser(page);
    });

    test("shows name prompt when name not set", async ({ page }) => {
      // loginAsRandomUser already navigates to /app
      const namePrompt = page.locator('[data-label="non-admin-name-prompt"]');
      await expect(namePrompt).toBeVisible({ timeout: 15000 });
    });

    test("chat input bar is enabled", async ({ page }) => {
      await expect(page.locator("#onyx-chat-input")).toBeVisible({
        timeout: 15000,
      });

      const chatInput = page.locator("#onyx-chat-input");
      await expect(chatInput).not.toHaveAttribute("aria-disabled", "true");
    });

    test("after setting name, shows confirmation then no onboarding UI", async ({
      page,
    }) => {
      const namePrompt = page.locator('[data-label="non-admin-name-prompt"]');
      await expect(namePrompt).toBeVisible({ timeout: 15000 });

      await namePrompt.getByPlaceholder("Your name").fill("E2E User");
      await namePrompt.getByRole("button", { name: "Save" }).click();

      // Confirmation should appear
      const confirmation = page.locator(
        '[data-label="non-admin-confirmation"]'
      );
      await expect(confirmation).toBeVisible({ timeout: 10000 });

      await expectElementScreenshot(confirmation, {
        name: "onboarding-nonadmin-with-llm-confirmation",
      });

      // Dismiss the confirmation
      await confirmation.getByRole("button").first().click();

      // No onboarding UI should remain
      await expect(namePrompt).not.toBeVisible({ timeout: 5000 });
      await expect(confirmation).not.toBeVisible();
    });
  });
});
