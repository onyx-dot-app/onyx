import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs, loginAsRandomUser, apiLogin } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { CraftWelcomePage } from "@tests/e2e/pages/CraftWelcomePage";

/**
 * Craft Provider Onboarding E2E Tests
 *
 * Covers the inline LLM-provider setup on the craft welcome page:
 * 1. Admin WITHOUT providers -> inline provider cards, input disabled;
 *    clicking a card opens the shared provider modal; the recommended-only
 *    toggle expands the catalog
 * 2. Non-admin WITHOUT providers -> inline locked state, input disabled
 * 3. Admin WITH provider -> no setup section, input enabled
 *
 * Marked @exclusive because scenarios 1 & 2 delete all LLM providers.
 * The whole suite is skipped when the deployment has craft disabled.
 */

async function craftEnabled(page: Page): Promise<boolean> {
  const response = await page.request.get("/api/settings");
  if (!response.ok()) return false;
  const settings = await response.json();
  return settings?.settings?.onyx_craft_enabled === true;
}

async function deleteAllProviders(client: OnyxApiClient): Promise<void> {
  const providers = await client.listLlmProviders();
  for (const provider of providers) {
    try {
      await client.deleteProvider(provider.id, { force: true });
    } catch (error) {
      console.warn(
        `Failed to delete provider ${provider.id}: ${String(error)}`
      );
    }
  }
}

async function createFreshAdmin(page: Page): Promise<void> {
  await page.context().clearCookies();
  const { email, password } = await loginAsRandomUser(page, {
    setDisplayName: false,
  });

  await page.context().clearCookies();
  await loginAs(page, "admin");
  const adminClient = new OnyxApiClient(page.request);
  await adminClient.setUserRole(email, "admin");

  await page.context().clearCookies();
  await apiLogin(page, email, password);
}

async function createFreshUser(page: Page): Promise<void> {
  await page.context().clearCookies();
  await loginAsRandomUser(page, { setDisplayName: false });
}

test.describe("Craft Provider Onboarding @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    test.skip(!(await craftEnabled(page)), "Craft is disabled");
  });

  test.describe("Admin WITHOUT providers", () => {
    test.beforeEach(async ({ page }) => {
      const adminClient = new OnyxApiClient(page.request);
      await deleteAllProviders(adminClient);
      await createFreshAdmin(page);
    });

    test.afterEach(async ({ page }) => {
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await adminClient.ensurePublicProvider();
    });

    test("shows inline LLM setup with disabled input and working toggle", async ({
      page,
    }) => {
      const welcome = new CraftWelcomePage(page);
      await welcome.goto();
      await welcome.dismissIntro();

      await expect(welcome.llmSetup).toBeVisible({ timeout: 15000 });
      await welcome.expectInputDisabled();

      // Recommended-only by default: the 3 build-mode providers
      await expect(welcome.providerCard("Claude")).toBeVisible();
      await expect(welcome.providerCard("GPT")).toBeVisible();
      await expect(welcome.providerCard("OpenRouter")).toBeVisible();
      await expect(welcome.providerCard("Gemini")).not.toBeVisible();

      // Toggle off reveals the full catalog
      await welcome.toggleRecommendedOnly();
      await expect(welcome.providerCard("Gemini")).toBeVisible();

      // Clicking a provider card opens the shared provider modal
      await welcome.openProviderSetup("Claude");
    });
  });

  test.describe("Non-admin WITHOUT providers", () => {
    test.beforeEach(async ({ page }) => {
      const adminClient = new OnyxApiClient(page.request);
      await deleteAllProviders(adminClient);
      await createFreshUser(page);
    });

    test.afterEach(async ({ page }) => {
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await adminClient.ensurePublicProvider();
    });

    test("shows inline locked state with disabled input", async ({ page }) => {
      const welcome = new CraftWelcomePage(page);
      await welcome.goto();
      await welcome.dismissIntro();

      await expect(welcome.lockedState).toBeVisible({ timeout: 15000 });
      await expect(welcome.llmSetup).not.toBeVisible();
      await welcome.expectInputDisabled();
    });
  });

  test.describe("Admin WITH provider", () => {
    test.beforeEach(async ({ page }) => {
      const adminClient = new OnyxApiClient(page.request);
      await adminClient.ensurePublicProvider();
      await createFreshAdmin(page);
    });

    test("no setup section and input enabled", async ({ page }) => {
      const welcome = new CraftWelcomePage(page);
      await welcome.goto();
      await welcome.dismissIntro();

      await expect(welcome.llmSetup).not.toBeVisible();
      await expect(welcome.lockedState).not.toBeVisible();
      await welcome.expectInputEnabled();
    });
  });
});
