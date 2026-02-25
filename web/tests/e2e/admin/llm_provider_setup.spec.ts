import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const LLM_CONFIG_URL = "/admin/configuration/llm";
const BASE_URL = process.env.BASE_URL || "http://localhost:3000";
const PROVIDER_API_KEY =
  process.env.E2E_LLM_PROVIDER_API_KEY ||
  process.env.OPENAI_API_KEY ||
  "e2e-placeholder-api-key-not-used";

type AdminLLMProvider = {
  id: number;
  name: string;
  is_auto_mode: boolean;
};

type AdminLLMProviderResponse = {
  providers: AdminLLMProvider[];
  default_text: { provider_id: number; model_name: string } | null;
};

function uniqueName(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function listAdminLLMProviders(
  page: Page
): Promise<AdminLLMProviderResponse> {
  const response = await page.request.get(`${BASE_URL}/api/admin/llm/provider`);
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as AdminLLMProviderResponse;
}

async function getProviderByName(
  page: Page,
  providerName: string
): Promise<AdminLLMProvider | null> {
  const { providers } = await listAdminLLMProviders(page);
  return providers.find((provider) => provider.name === providerName) ?? null;
}

async function createPublicProvider(
  page: Page,
  providerName: string
): Promise<number> {
  const response = await page.request.put(
    `${BASE_URL}/api/admin/llm/provider?is_creation=true`,
    {
      data: {
        name: providerName,
        provider: "openai",
        api_key: PROVIDER_API_KEY,
        default_model_name: "gpt-4o",
        is_public: true,
        groups: [],
        personas: [],
      },
    }
  );
  expect(response.ok()).toBeTruthy();
  const data = (await response.json()) as { id: number };
  return data.id;
}

/**
 * Find the provider card in the "Available Providers" section by name.
 */
async function findExistingProviderCard(
  page: Page,
  providerName: string
): Promise<Locator> {
  return page
    .locator("div")
    .filter({ hasText: providerName })
    .filter({ has: page.locator("button[aria-label='Settings']") })
    .first();
}

/**
 * Find the "Add Provider" card for a well-known provider (e.g. "OpenAI").
 */
async function findNewProviderCard(
  page: Page,
  providerProductName: string
): Promise<Locator> {
  return page
    .locator("div")
    .filter({ hasText: providerProductName })
    .filter({ has: page.getByRole("button", { name: "Connect" }) })
    .first();
}

/**
 * Open the setup modal for a well-known provider from the "Add Provider" grid.
 */
async function openSetupModal(
  page: Page,
  providerProductName: string
): Promise<Locator> {
  const card = await findNewProviderCard(page, providerProductName);
  await expect(card).toBeVisible({ timeout: 10000 });
  await card.getByRole("button", { name: "Connect" }).click();

  const modal = page.getByRole("dialog");
  await expect(modal).toBeVisible({ timeout: 10000 });
  return modal;
}

/**
 * Open the edit modal for an existing provider via the settings icon.
 */
async function openEditModal(
  page: Page,
  providerName: string
): Promise<Locator> {
  const card = await findExistingProviderCard(page, providerName);
  await expect(card).toBeVisible({ timeout: 10000 });
  await card.locator("button[aria-label='Settings']").click();

  const modal = page.getByRole("dialog");
  await expect(modal).toBeVisible({ timeout: 10000 });
  return modal;
}

/**
 * Click the trash icon on an existing provider card to open the delete confirmation.
 */
async function openDeleteConfirmation(
  page: Page,
  providerName: string
): Promise<Locator> {
  const card = await findExistingProviderCard(page, providerName);
  await expect(card).toBeVisible({ timeout: 10000 });
  await card.locator("button[aria-label='Trash']").click();

  const modal = page.getByRole("dialog", { name: /delete llm provider/i });
  await expect(modal).toBeVisible({ timeout: 10000 });
  return modal;
}

test.describe("LLM Provider Setup @exclusive", () => {
  let providersToCleanup: number[] = [];

  test.beforeEach(async ({ page }) => {
    providersToCleanup = [];
    await page.context().clearCookies();
    await loginAs(page, "admin");
    await page.goto(LLM_CONFIG_URL);
    await page.waitForLoadState("networkidle");
    await expect(page.getByLabel("admin-page-title")).toHaveText(/^LLM Models/);
  });

  test.afterEach(async ({ page }) => {
    const apiClient = new OnyxApiClient(page.request);
    const uniqueIds = Array.from(new Set(providersToCleanup));

    for (const providerId of uniqueIds) {
      try {
        await apiClient.deleteProvider(providerId);
      } catch (error) {
        console.warn(
          `Cleanup failed for provider ${providerId}: ${String(error)}`
        );
      }
    }
  });

  test("admin can create, edit, and delete a provider", async ({ page }) => {
    // Mock the test endpoint so we don't need real LLM connectivity.
    await page.route("**/api/admin/llm/test", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
    });

    const providerName = uniqueName("PW OpenAI Provider");

    // ── Create ──
    const setupModal = await openSetupModal(page, "OpenAI");
    await setupModal.getByLabel("Display Name").fill(providerName);
    await setupModal.getByLabel("API Key").fill(PROVIDER_API_KEY);

    const enableButton = setupModal.getByRole("button", { name: "Enable" });
    await expect(enableButton).toBeEnabled({ timeout: 10000 });
    await enableButton.click();
    await expect(setupModal).not.toBeVisible({ timeout: 30000 });

    await expect
      .poll(
        async () => (await getProviderByName(page, providerName))?.id ?? null
      )
      .not.toBeNull();

    const createdProvider = await getProviderByName(page, providerName);
    expect(createdProvider).not.toBeNull();
    providersToCleanup.push(createdProvider!.id);

    // ── Edit ──
    await page.reload();
    await page.waitForLoadState("networkidle");

    const editModal = await openEditModal(page, providerName);
    const autoUpdateSwitch = editModal.getByRole("switch").first();
    const initialAutoModeState =
      (await autoUpdateSwitch.getAttribute("aria-checked")) === "true";
    await autoUpdateSwitch.click();

    const updateButton = editModal.getByRole("button", { name: "Update" });
    await expect(updateButton).toBeEnabled({ timeout: 10000 });
    await updateButton.click();
    await expect(editModal).not.toBeVisible({ timeout: 30000 });

    await expect
      .poll(async () => {
        const provider = await getProviderByName(page, providerName);
        return provider?.is_auto_mode;
      })
      .toBe(!initialAutoModeState);

    // ── Delete (via confirmation modal) ──
    await page.reload();
    await page.waitForLoadState("networkidle");

    const deleteModal = await openDeleteConfirmation(page, providerName);
    await expect(deleteModal.getByText("permanently delete")).toBeVisible();

    await deleteModal.getByRole("button", { name: "Delete" }).click();
    await expect(deleteModal).not.toBeVisible({ timeout: 15000 });

    await expect
      .poll(
        async () => (await getProviderByName(page, providerName))?.id ?? null
      )
      .toBeNull();

    providersToCleanup = providersToCleanup.filter(
      (id) => id !== createdProvider!.id
    );
  });

  test("admin can change the default model via the dropdown", async ({
    page,
  }) => {
    const apiClient = new OnyxApiClient(page.request);
    const { default_text: initialDefault } = await listAdminLLMProviders(page);

    const providerName = uniqueName("PW Default Test Provider");
    const providerId = await createPublicProvider(page, providerName);
    providersToCleanup.push(providerId);

    await apiClient.setProviderAsDefault(providerId, "gpt-4o");

    await page.reload();
    await page.waitForLoadState("networkidle");

    // The Default Model card should be visible
    await expect(page.getByText("Default Model")).toBeVisible({
      timeout: 10000,
    });

    // The provider should appear in the Available Providers section with "Default" tag
    const providerCard = await findExistingProviderCard(page, providerName);
    await expect(providerCard).toBeVisible({ timeout: 10000 });
    await expect(providerCard.getByText("Default")).toBeVisible();

    // Restore initial default if there was one
    if (initialDefault) {
      try {
        await apiClient.setProviderAsDefault(
          initialDefault.provider_id,
          initialDefault.model_name
        );
      } catch (error) {
        console.warn(`Failed to restore initial default: ${String(error)}`);
      }
    }
  });

  test("delete confirmation warns when deleting the default provider", async ({
    page,
  }) => {
    const apiClient = new OnyxApiClient(page.request);
    const { default_text: initialDefault } = await listAdminLLMProviders(page);

    const providerName = uniqueName("PW Default Delete Test");
    const providerId = await createPublicProvider(page, providerName);
    providersToCleanup.push(providerId);

    await apiClient.setProviderAsDefault(providerId, "gpt-4o");

    await page.reload();
    await page.waitForLoadState("networkidle");

    const deleteModal = await openDeleteConfirmation(page, providerName);

    // Should show the default provider warning
    await expect(deleteModal.getByText("default provider")).toBeVisible();

    // Cancel instead of deleting
    await deleteModal.getByRole("button", { name: "Cancel" }).click();
    await expect(deleteModal).not.toBeVisible({ timeout: 5000 });

    // Provider should still exist
    const provider = await getProviderByName(page, providerName);
    expect(provider).not.toBeNull();

    // Restore initial default if there was one
    if (initialDefault) {
      try {
        await apiClient.setProviderAsDefault(
          initialDefault.provider_id,
          initialDefault.model_name
        );
      } catch (error) {
        console.warn(`Failed to restore initial default: ${String(error)}`);
      }
    }
  });
});
