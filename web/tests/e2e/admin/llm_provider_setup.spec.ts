import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const LLM_SETUP_URL = "/admin/configuration/language-models";
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

type ProviderModelConfig = {
  name: string;
  is_visible: boolean;
};

function uniqueName(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function normalizeAlphaNum(input: string): string {
  return input.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function modelTokenVariants(modelName: string): string[][] {
  return modelName
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((token) => token.length > 0)
    .map((token) => {
      // Display names may shorten long numeric segments to suffixes.
      if (/^\d+$/.test(token) && token.length > 5) {
        return [token, token.slice(-5)];
      }
      return [token];
    });
}

function textMatchesModel(modelName: string, candidateText: string): boolean {
  const normalizedCandidate = normalizeAlphaNum(candidateText);
  if (!normalizedCandidate) {
    return false;
  }

  const tokenVariants = modelTokenVariants(modelName);
  return tokenVariants.every((variants) =>
    variants.some((variant) =>
      normalizedCandidate.includes(normalizeAlphaNum(variant))
    )
  );
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
  return createPublicProviderWithModels(page, providerName, [
    { name: modelName, is_visible: true },
  ]);
}

async function createPublicProviderWithModels(
  page: Page,
  providerName: string,
  modelConfigurations: ProviderModelConfig[]
): Promise<number> {
  expect(modelConfigurations.length).toBeGreaterThan(0);

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
        model_configurations: modelConfigurations,
      },
    }
  );
  expect(response.ok()).toBeTruthy();
  const data = (await response.json()) as { id: number };
  return data.id;
}

async function navigateToAdminLlmPageFromChat(page: Page): Promise<void> {
  await page.goto(LLM_SETUP_URL);
  await page.waitForURL("**/admin/configuration/language-models**");
  await expect(page.getByLabel("admin-page-title")).toHaveText(
    /^Language Models/
  );
}

async function exitAdminToChat(page: Page): Promise<void> {
  await page.goto("/app");
  await page.waitForURL("**/app**");
  await page
    .locator("#onyx-chat-input-textarea")
    .waitFor({ state: "visible", timeout: 15000 });
}

async function isModelVisibleInChatProviders(
  page: Page,
  modelName: string
): Promise<boolean> {
  const response = await page.request.get(`${BASE_URL}/api/llm/provider`);
  expect(response.ok()).toBeTruthy();

  const data = (await response.json()) as {
    providers: {
      model_configurations: { name: string; is_visible: boolean }[];
    }[];
  };

  return data.providers.some((provider) =>
    provider.model_configurations.some(
      (model) => model.name === modelName && model.is_visible
    )
  );
}

async function expectModelVisibilityInChatProviders(
  page: Page,
  modelName: string,
  expectedVisible: boolean
): Promise<void> {
  await expect
    .poll(() => isModelVisibleInChatProviders(page, modelName), {
      timeout: 30000,
    })
    .toBe(expectedVisible);
}

async function getModelCountInChatSelector(
  page: Page,
  modelName: string
): Promise<number> {
  const dialog = page.locator('[role="dialog"]').first();

  // When used in expect.poll retries, a previous attempt may leave the
  // popover open. Ensure a clean state before toggling it.
  if (await dialog.isVisible()) {
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "hidden", timeout: 5000 });
  }

  await page.getByTestId("model-selector").locator("button").first().click();
  await dialog.waitFor({ state: "visible", timeout: 10000 });

  await dialog.getByPlaceholder("Search models...").fill(modelName);
  const optionButtons = dialog.getByRole("button");
  const optionTexts = await optionButtons.allTextContents();
  const uniqueOptionTexts = Array.from(
    new Set(optionTexts.map((text) => text.trim()))
  );
  const count = uniqueOptionTexts.filter((text) =>
    textMatchesModel(modelName, text)
  ).length;

  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden", timeout: 10000 });

  return count;
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
  return page
    .locator("div.rounded-16")
    .filter({ hasText: providerName })
    .first();
}

async function openOpenAiSetupModal(page: Page): Promise<Locator> {
  const openAiCard = page
    .locator("div.rounded-16")
    .filter({ hasText: "OpenAI" })
    .filter({ has: page.getByRole("button", { name: "Connect" }) })
    .first();

  await expect(openAiCard).toBeVisible({ timeout: 10000 });
  await openAiCard.getByRole("button", { name: "Connect" }).click();

  const modal = page.getByRole("dialog", { name: /set up gpt/i });
  await expect(modal).toBeVisible({ timeout: 10000 });
  return modal;
}

async function openProviderEditModal(
  page: Page,
  providerName: string
): Promise<Locator> {
  const providerCard = await findProviderCard(page, providerName);
  await expect(providerCard).toBeVisible({ timeout: 10000 });
  await providerCard.getByRole("button", { name: /^Edit/ }).click();

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
    await expect(page.getByLabel("admin-page-title")).toHaveText(
      /^Language Models/
    );
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

    const enableButton = setupModal.getByRole("button", { name: "Connect" });
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

    const providerCard = await findProviderCard(page, providerName);
    await providerCard.hover();
    await providerCard.getByRole("button", { name: /^Delete/ }).click();
    const confirmationModal = page.getByRole("dialog");
    await expect(confirmationModal).toBeVisible({ timeout: 10000 });
    await confirmationModal.getByRole("button", { name: "Delete" }).click();
    await expect(confirmationModal).not.toBeVisible({ timeout: 15000 });

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

  test("adding a hidden model on an existing provider shows it in chat after one save", async ({
    page,
  }) => {
    await page.route("**/api/admin/llm/test", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
    });

    const providerName = uniqueName("PW Provider Add Model");
    const ts = Date.now();
    const alwaysVisibleModel = `pw-visible-${ts}-base`;
    const modelToEnable = `pw-hidden-${ts}-to-enable`;

    const providerId = await createPublicProviderWithModels(
      page,
      providerName,
      [
        { name: alwaysVisibleModel, is_visible: true },
        { name: modelToEnable, is_visible: false },
      ]
    );
    providersToCleanup.push(providerId);
    await expectModelVisibilityInChatProviders(page, modelToEnable, false);

    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page
      .locator("#onyx-chat-input-textarea")
      .waitFor({ state: "visible", timeout: 15000 });

    await expect
      .poll(() => getModelCountInChatSelector(page, modelToEnable), {
        timeout: 15000,
      })
      .toBe(0);

    await navigateToAdminLlmPageFromChat(page);

    const editModal = await openProviderEditModal(page, providerName);
    await editModal.getByText(modelToEnable, { exact: true }).click();

    const updateButton = editModal.getByRole("button", { name: "Update" });
    const providerUpdateResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/api/admin/llm/provider") &&
        response.request().method() === "PUT"
    );
    await expect(updateButton).toBeEnabled({ timeout: 10000 });
    await updateButton.click();
    await providerUpdateResponsePromise;
    await expect(editModal).not.toBeVisible({ timeout: 30000 });
    await expectModelVisibilityInChatProviders(page, modelToEnable, true);

    await exitAdminToChat(page);
    await expect
      .poll(() => getModelCountInChatSelector(page, modelToEnable), {
        timeout: 15000,
      })
      .toBe(1);
  });

  test("removing a visible model on an existing provider hides it in chat after one save", async ({
    page,
  }) => {
    await page.route("**/api/admin/llm/test", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
    });

    const providerName = uniqueName("PW Provider Remove Model");
    const ts = Date.now();
    const alwaysVisibleModel = `pw-visible-${ts}-base`;
    const modelToDisable = `pw-visible-${ts}-to-disable`;

    const providerId = await createPublicProviderWithModels(
      page,
      providerName,
      [
        { name: alwaysVisibleModel, is_visible: true },
        { name: modelToDisable, is_visible: true },
      ]
    );
    providersToCleanup.push(providerId);
    await expectModelVisibilityInChatProviders(page, modelToDisable, true);

    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page
      .locator("#onyx-chat-input-textarea")
      .waitFor({ state: "visible", timeout: 15000 });

    await expect
      .poll(() => getModelCountInChatSelector(page, modelToDisable), {
        timeout: 15000,
      })
      .toBe(1);

    await navigateToAdminLlmPageFromChat(page);

    const editModal = await openProviderEditModal(page, providerName);
    await editModal.getByText(modelToDisable, { exact: true }).click();

    const updateButton = editModal.getByRole("button", { name: "Update" });
    const providerUpdateResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/api/admin/llm/provider") &&
        response.request().method() === "PUT"
    );
    await expect(updateButton).toBeEnabled({ timeout: 10000 });
    await updateButton.click();
    await providerUpdateResponsePromise;
    await expect(editModal).not.toBeVisible({ timeout: 30000 });
    await expectModelVisibilityInChatProviders(page, modelToDisable, false);

    await exitAdminToChat(page);
    await expect
      .poll(() => getModelCountInChatSelector(page, modelToDisable), {
        timeout: 15000,
      })
      .toBe(0);
  });
});
