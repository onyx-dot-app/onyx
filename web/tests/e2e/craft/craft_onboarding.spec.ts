import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs, loginAsRandomUser, apiLogin } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

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

async function dismissIntro(page: Page): Promise<void> {
  const intro = page.getByText("What is Onyx Craft?");
  await expect(intro).toBeVisible({ timeout: 15000 });
  await page.getByRole("button", { name: "Get Started!" }).click();
  await expect(intro).not.toBeVisible();
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
      await page.goto("/craft/v1");
      await dismissIntro(page);

      const llmSetup = page.locator('[aria-label="craft-llm-setup"]');
      await expect(llmSetup).toBeVisible({ timeout: 15000 });

      const messageInput = page.locator('[aria-label="Message input"]');
      await expect(messageInput).toHaveAttribute("aria-disabled", "true");

      // Recommended-only by default: the 3 build-mode providers
      await expect(llmSetup.getByText("Claude")).toBeVisible();
      await expect(llmSetup.getByText("GPT")).toBeVisible();
      await expect(llmSetup.getByText("OpenRouter")).toBeVisible();
      await expect(llmSetup.getByText("Gemini")).not.toBeVisible();

      // Toggle off reveals the full catalog
      await llmSetup.getByRole("switch").click();
      await expect(llmSetup.getByText("Gemini")).toBeVisible();

      // Clicking a provider card opens the shared provider modal
      await llmSetup.getByText("Claude").click();
      await expect(page.getByText("Set up Claude")).toBeVisible({
        timeout: 10000,
      });
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
      await page.goto("/craft/v1");
      await dismissIntro(page);

      const locked = page.locator('[aria-label="craft-llm-locked"]');
      await expect(locked).toBeVisible({ timeout: 15000 });
      await expect(
        page.locator('[aria-label="craft-llm-setup"]')
      ).not.toBeVisible();

      const messageInput = page.locator('[aria-label="Message input"]');
      await expect(messageInput).toHaveAttribute("aria-disabled", "true");
    });
  });

  test.describe("Admin WITH provider", () => {
    test.beforeEach(async ({ page }) => {
      const adminClient = new OnyxApiClient(page.request);
      await adminClient.ensurePublicProvider();
      await createFreshAdmin(page);
    });

    test("no setup section and input enabled", async ({ page }) => {
      await page.goto("/craft/v1");
      await dismissIntro(page);

      await expect(
        page.locator('[aria-label="craft-llm-setup"]')
      ).not.toBeVisible();
      await expect(
        page.locator('[aria-label="craft-llm-locked"]')
      ).not.toBeVisible();

      const messageInput = page.locator('[aria-label="Message input"]');
      await expect(messageInput).toBeVisible({ timeout: 15000 });
      await expect(messageInput).toHaveAttribute("aria-disabled", "false");
    });
  });
});
