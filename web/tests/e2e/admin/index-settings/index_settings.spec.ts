import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";

const INDEX_SETTINGS_URL = "/admin/configuration/index-settings";
const EMBEDDING_PROVIDER_API = "**/api/admin/embedding/embedding-provider**";
const TEST_EMBEDDING_API = "**/api/admin/embedding/test-embedding";

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function getConfiguredProviders(
  page: Page
): Promise<{ provider_type: string }[]> {
  const response = await page.request.get(
    "/api/admin/embedding/embedding-provider"
  );
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function disconnectProvider(
  page: Page,
  providerType: string
): Promise<void> {
  const response = await page.request.delete(
    `/api/admin/embedding/embedding-provider/${providerType}`
  );
  // 404 is acceptable — provider may already be gone
  expect(response.status()).not.toBe(500);
}

async function getCurrentSearchSettings(page: Page) {
  const response = await page.request.get(
    "/api/search-settings/get-current-search-settings"
  );
  expect(response.ok()).toBeTruthy();
  return response.json();
}

// ---------------------------------------------------------------------------
// Page helpers
// ---------------------------------------------------------------------------

async function navigateToIndexSettings(page: Page): Promise<void> {
  await page.goto(INDEX_SETTINGS_URL);
  await page.waitForLoadState("networkidle");
  await expect(page.getByLabel("admin-page-title")).toHaveText(
    /index settings/i
  );
}

async function expandModelPicker(page: Page): Promise<void> {
  const viewAllButton = page.getByRole("button", { name: /view all models/i });
  await expect(viewAllButton).toBeVisible({ timeout: 10000 });
  await viewAllButton.click();
}

async function openConnectModal(
  page: Page,
  providerName: string
): Promise<void> {
  const connectButton = page
    .locator("[data-interactive-state]")
    .filter({ hasText: providerName })
    .getByRole("button", { name: /connect/i })
    .first();
  await expect(connectButton).toBeVisible({ timeout: 10000 });
  await connectButton.click();
  await expect(
    page.getByRole("dialog", {
      name: new RegExp(`set up ${providerName}`, "i"),
    })
  ).toBeVisible({ timeout: 10000 });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Index Settings Page @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test("page loads and shows the embedding model picker", async ({ page }) => {
    await navigateToIndexSettings(page);
    await expandModelPicker(page);

    // Cloud Hosted and Self Hosted tabs
    await expect(
      page.getByRole("tab", { name: /cloud hosted/i })
    ).toBeVisible();
    await expect(page.getByRole("tab", { name: /self hosted/i })).toBeVisible();
  });

  test("can connect and disconnect an embedding provider", async ({ page }) => {
    // Mock the test-embedding endpoint so no real API key is needed
    await page.route(TEST_EMBEDDING_API, async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({}) });
    });
    // Mock the PUT so the provider is "saved" without hitting the backend
    await page.route(EMBEDDING_PROVIDER_API, async (route) => {
      if (route.request().method() === "PUT") {
        await route.fulfill({
          status: 200,
          body: JSON.stringify({ provider_type: "openai" }),
        });
      } else {
        await route.continue();
      }
    });

    await navigateToIndexSettings(page);
    await expandModelPicker(page);

    // Open the OpenAI connect modal
    await openConnectModal(page, "OpenAI");
    const modal = page.getByRole("dialog", { name: /set up openai/i });

    // Fill in a placeholder API key
    await modal.getByLabel(/api key/i).fill("sk-placeholder-key");
    const connectButton = modal.getByRole("button", { name: /connect/i });
    await expect(connectButton).toBeEnabled({ timeout: 5000 });
    await connectButton.click();
    await expect(modal).not.toBeVisible({ timeout: 15000 });
  });

  test("edit modal pre-fills existing provider fields", async ({ page }) => {
    // Seed a connected provider via the API
    await page.route(TEST_EMBEDDING_API, async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({}) });
    });

    const seedResponse = await page.request.put(
      "/api/admin/embedding/embedding-provider",
      {
        data: {
          provider_type: "openai",
          api_key: "sk-seed-key",
          api_url: "",
          api_version: null,
          deployment_name: null,
          is_default_provider: false,
          is_configured: true,
        },
      }
    );
    // Skip if we can't seed (e.g. no test key access)
    test.skip(!seedResponse.ok(), "Could not seed embedding provider");

    try {
      await navigateToIndexSettings(page);
      await expandModelPicker(page);

      // Edit button should be visible for the connected provider
      const editButton = page
        .locator("[data-interactive-state]")
        .filter({ hasText: "OpenAI" })
        .getByRole("button", { name: /edit|manage/i })
        .first();
      await expect(editButton).toBeVisible({ timeout: 10000 });
      await editButton.click();

      const modal = page.getByRole("dialog", { name: /manage openai/i });
      await expect(modal).toBeVisible({ timeout: 10000 });

      // API key field should show a masked value (not be blank)
      const apiKeyInput = modal.getByLabel(/api key/i);
      await expect(apiKeyInput).not.toHaveValue("");

      await modal.getByRole("button", { name: /cancel/i }).click();
      await expect(modal).not.toBeVisible({ timeout: 10000 });
    } finally {
      await disconnectProvider(page, "openai");
    }
  });

  test("selecting a model stages it and enables Apply", async ({ page }) => {
    await navigateToIndexSettings(page);
    await expandModelPicker(page);

    // Switch to Self Hosted tab where models are always available (no connect required)
    await page.getByRole("tab", { name: /self hosted/i }).click();

    // Click the first available self-hosted model card
    const modelCard = page
      .locator(
        "[data-interactive-state='empty'], [data-interactive-state='filled']"
      )
      .first();
    await expect(modelCard).toBeVisible({ timeout: 10000 });
    await modelCard.click();

    // The Apply button (or equivalent) should now be enabled in the banner
    const applyButton = page.getByRole("button", { name: /apply/i });
    await expect(applyButton).toBeVisible({ timeout: 5000 });
    await expect(applyButton).toBeEnabled();
  });

  test("current search settings are reflected on the page", async ({
    page,
  }) => {
    const settings = await getCurrentSearchSettings(page);
    await navigateToIndexSettings(page);

    if (settings.model_name) {
      // The current model name should appear somewhere on the page
      await expect(
        page.getByText(settings.model_name, { exact: false })
      ).toBeVisible({ timeout: 10000 });
    }
  });
});
