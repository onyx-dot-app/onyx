import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const LLM_SETUP_URL = "/admin/configuration/llm";
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

type DefaultModelInfo = {
  provider_id: number;
  model_name: string;
} | null;

function uniqueName(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function getAdminLLMProviderResponse(page: Page) {
  const response = await page.request.get(`${BASE_URL}/api/admin/llm/provider`);
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as {
    providers: AdminLLMProvider[];
    default_text: DefaultModelInfo;
    default_vision: DefaultModelInfo;
  };
}

async function listAdminLLMProviders(page: Page): Promise<AdminLLMProvider[]> {
  const data = await getAdminLLMProviderResponse(page);
  return data.providers;
}

async function getDefaultTextModel(page: Page): Promise<DefaultModelInfo> {
  const data = await getAdminLLMProviderResponse(page);
  return data.default_text ?? null;
}

async function createPublicProvider(
  page: Page,
  providerName: string,
  modelName: string = "gpt-4o"
): Promise<number> {
  const response = await page.request.put(
    `${BASE_URL}/api/admin/llm/provider?is_creation=true`,
    {
      data: {
        name: providerName,
        provider: "openai",
        api_key: PROVIDER_API_KEY,
        is_public: true,
        groups: [],
        personas: [],
        model_configurations: [{ name: modelName, is_visible: true }],
      },
    }
  );
  expect(response.ok()).toBeTruthy();
  const data = (await response.json()) as { id: number };
  return data.id;
}

async function getProviderByName(
  page: Page,
  providerName: string
): Promise<AdminLLMProvider | null> {
  const providers = await listAdminLLMProviders(page);
  return providers.find((provider) => provider.name === providerName) ?? null;
}

async function findProviderCard(
  page: Page,
  providerName: string
): Promise<Locator> {
  return page.locator("div.card").filter({ hasText: providerName }).first();
}

async function openOpenAiSetupModal(page: Page): Promise<Locator> {
  const openAiCard = page
    .locator("div.card")
    .filter({ hasText: "OpenAI" })
    .filter({ has: page.getByRole("button", { name: "Connect" }) })
    .first();

  await expect(openAiCard).toBeVisible({ timeout: 10000 });
  await openAiCard.getByRole("button", { name: "Connect" }).click();

  const modal = page.getByRole("dialog", { name: /setup openai/i });
  await expect(modal).toBeVisible({ timeout: 10000 });
  return modal;
}

async function openProviderEditModal(
  page: Page,
  providerName: string
): Promise<Locator> {
  const providerCard = await findProviderCard(page, providerName);
  await expect(providerCard).toBeVisible({ timeout: 10000 });
  await providerCard.getByRole("button", { name: "Edit provider" }).click();

  const modal = page.getByRole("dialog", { name: /configure/i });
  await expect(modal).toBeVisible({ timeout: 10000 });
  return modal;
}

test.describe("LLM Provider Setup @exclusive", () => {
  let providersToCleanup: number[] = [];

  test.beforeEach(async ({ page }) => {
    providersToCleanup = [];
    await page.context().clearCookies();
    await loginAs(page, "admin");
    await page.goto(LLM_SETUP_URL);
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

  test("admin can create, edit, and delete a provider from the LLM setup page", async ({
    page,
  }) => {
    // Keep this flow deterministic without external LLM connectivity.
    await page.route("**/api/admin/llm/test", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
    });

    const providerName = uniqueName("PW OpenAI Provider");
    const apiKey = PROVIDER_API_KEY;

    const setupModal = await openOpenAiSetupModal(page);
    await setupModal.getByLabel("Display Name").fill(providerName);
    await setupModal.getByLabel("API Key").fill(apiKey);

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

    const editModal = await openProviderEditModal(page, providerName);
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

    const deleteModal = await openProviderEditModal(page, providerName);
    await deleteModal.getByRole("button", { name: "Delete" }).click();
    await expect(deleteModal).not.toBeVisible({ timeout: 15000 });

    await expect
      .poll(
        async () => (await getProviderByName(page, providerName))?.id ?? null
      )
      .toBeNull();

    providersToCleanup = providersToCleanup.filter(
      (providerId) => providerId !== createdProvider!.id
    );
  });

  test("admin can switch the default model via the default model dropdown", async ({
    page,
  }) => {
    const apiClient = new OnyxApiClient(page.request);
    const initialDefault = await getDefaultTextModel(page);

    const firstProviderName = uniqueName("PW Baseline Provider");
    const secondProviderName = uniqueName("PW Target Provider");
    const firstModelName = "gpt-4o";
    const secondModelName = "gpt-4o-mini";

    const firstProviderId = await createPublicProvider(
      page,
      firstProviderName,
      firstModelName
    );
    const secondProviderId = await createPublicProvider(
      page,
      secondProviderName,
      secondModelName
    );
    providersToCleanup.push(firstProviderId, secondProviderId);

    try {
      await apiClient.setProviderAsDefault(firstProviderId, firstModelName);

      await page.reload();
      await page.waitForLoadState("networkidle");

      // Open the Default Model dropdown and select the model from the
      // second provider's group (scoped to avoid picking a same-named model
      // from another provider).
      await page.getByRole("combobox").click();
      const targetGroup = page
        .locator('[role="group"]')
        .filter({ hasText: secondProviderName });
      const defaultResponsePromise = page.waitForResponse(
        (response) =>
          response.url().includes("/api/admin/llm/default") &&
          response.request().method() === "POST"
      );
      await targetGroup.locator('[role="option"]').click();
      await defaultResponsePromise;

      // Verify the default switched to the second provider
      await expect
        .poll(async () => {
          const defaultText = await getDefaultTextModel(page);
          return defaultText?.provider_id;
        })
        .toBe(secondProviderId);
    } finally {
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
    }
  });
});
