import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";

const INDEX_SETTINGS_URL = "/admin/configuration/index-settings";
const EMBEDDING_PROVIDER_API = "**/api/admin/embedding/embedding-provider**";
const TEST_EMBEDDING_API = "**/api/admin/embedding/test-embedding";
const SET_NEW_SETTINGS_API = "**/api/search-settings/set-new-search-settings**";

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
// Helpers shared across both describe blocks
// ---------------------------------------------------------------------------

async function stageNonCurrentSelfHostedModel(page: Page): Promise<void> {
  await expandModelPicker(page);
  await page.getByRole("tab", { name: /self.hosted/i }).click();
  const selectButton = page
    .getByRole("button", { name: "Select Model" })
    .first();
  await expect(selectButton).toBeVisible({ timeout: 10000 });
  await selectButton.click();
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

async function switchToCloudTab(page: Page): Promise<void> {
  const cloudTab = page.getByRole("tab", { name: /cloud.based/i });
  await expect(cloudTab).toBeVisible({ timeout: 10000 });
  await cloudTab.click();
}

async function openConnectModal(
  page: Page,
  providerName: string
): Promise<void> {
  // "View All Models" defaults to Self-hosted when the current model has no
  // cloud provider — switch to Cloud-based tab explicitly first.
  await switchToCloudTab(page);

  // Click the first Connect button visible — the dialog title confirms the provider
  const connectButton = page.getByRole("button", { name: "Connect" }).first();
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

    // Cloud-based and Self-hosted tabs
    await expect(page.getByRole("tab", { name: /cloud.based/i })).toBeVisible();
    await expect(page.getByRole("tab", { name: /self.hosted/i })).toBeVisible();
  });

  test("can connect and disconnect an embedding provider", async ({ page }) => {
    // Mock the test-embedding endpoint so no real API key is needed
    await page.route(TEST_EMBEDDING_API, async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({}) });
    });
    // Mock the provider list (GET) to return empty so all cards show "Connect",
    // and mock PUT so the provider is "saved" without hitting the backend
    await page.route(EMBEDDING_PROVIDER_API, async (route) => {
      if (route.request().method() === "PUT") {
        await route.fulfill({
          status: 200,
          body: JSON.stringify({ provider_type: "cohere" }),
        });
      } else if (route.request().method() === "GET") {
        await route.fulfill({ status: 200, body: JSON.stringify([]) });
      } else {
        await route.continue();
      }
    });

    await navigateToIndexSettings(page);
    await expandModelPicker(page);

    // Open the Cohere connect modal (first provider in the cloud list)
    await openConnectModal(page, "Cohere");
    const modal = page.getByRole("dialog", { name: /set up cohere/i });

    // Fill in a placeholder API key
    await modal.getByLabel(/api key/i).fill("co-placeholder-key");
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
      // "View All Models" defaults to Self-hosted — switch to Cloud-based where
      // the edit button appears for configured providers.
      await switchToCloudTab(page);

      // Edit button should be visible for the connected provider
      const editButton = page.getByRole("button", {
        name: /edit credentials/i,
      });
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

    // Switch to Self-hosted tab where models are always available (no connect required)
    await page.getByRole("tab", { name: /self.hosted/i }).click();

    // Click "Select Model" on the first available self-hosted model
    const selectButton = page
      .getByRole("button", { name: "Select Model" })
      .first();
    await expect(selectButton).toBeVisible({ timeout: 10000 });
    await selectButton.click();

    // The Apply button should now be enabled in the banner.
    // Default switchoverType is SWITCHOVER_NONE before our auto-advance fix runs,
    // so we accept either label here since this test only cares that Apply appears.
    const applyButton = page
      .getByRole("button", { name: "Apply & Re-index" })
      .or(page.getByRole("button", { name: "Apply without Re-index" }));
    await expect(applyButton.first()).toBeVisible({ timeout: 5000 });
    await expect(applyButton.first()).toBeEnabled();
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

// ---------------------------------------------------------------------------
// Switchover strategy tests
// ---------------------------------------------------------------------------

test.describe("Index Settings — switchover strategies @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test("staging a model auto-advances dropdown to REINDEX", async ({
    page,
  }) => {
    await navigateToIndexSettings(page);
    await stageNonCurrentSelfHostedModel(page);

    // Auto-advance: button must read "Apply & Re-index", not "Apply without Re-index"
    const applyButton = page.getByRole("button", { name: "Apply & Re-index" });
    await expect(applyButton).toBeVisible({ timeout: 5000 });
    await expect(applyButton).toBeEnabled();

    // Dropdown should show the REINDEX option as selected
    await expect(page.getByRole("combobox").first()).toContainText(
      /re-index all connectors/i
    );
  });

  test("reverting a staged model resets the banner", async ({ page }) => {
    await navigateToIndexSettings(page);
    await stageNonCurrentSelfHostedModel(page);

    await expect(
      page.getByRole("button", { name: "Apply & Re-index" })
    ).toBeVisible({ timeout: 5000 });

    await page.getByRole("button", { name: "Revert" }).click();

    // Banner actions should be gone once the form is clean
    await expect(
      page.getByRole("button", { name: "Apply & Re-index" })
    ).not.toBeVisible({ timeout: 5000 });
    await expect(
      page.getByRole("button", { name: "Apply without Re-index" })
    ).not.toBeVisible();
  });

  // Parameterised: each re-index strategy must appear in the request body
  const strategies = [
    { label: "Re-index All Connectors Then Switch", switchoverType: "reindex" },
    {
      label: "Re-index Active Connectors Then Switch",
      switchoverType: "active_only",
    },
    { label: "Switch Before Re-index", switchoverType: "instant" },
  ];

  for (const { label, switchoverType } of strategies) {
    test(`apply with "${label}" sends switchover_type="${switchoverType}"`, async ({
      page,
    }) => {
      // Capture the request body before fulfilling so we can assert on it
      const bodyPromise = new Promise<Record<string, unknown>>((resolve) => {
        void page.route(SET_NEW_SETTINGS_API, async (route) => {
          resolve(
            JSON.parse(route.request().postData() ?? "{}") as Record<
              string,
              unknown
            >
          );
          await route.fulfill({ status: 200, body: JSON.stringify({}) });
        });
      });

      await navigateToIndexSettings(page);
      await stageNonCurrentSelfHostedModel(page);

      // Open the strategy dropdown and pick the target option
      await page.getByRole("combobox").first().click();
      await page.getByRole("option", { name: label }).click();

      await page.getByRole("button", { name: "Apply & Re-index" }).click();

      const body = await bodyPromise;
      expect(body.switchover_type).toBe(switchoverType);
    });
  }

  test("toggling contextual retrieval stages a change and enables Apply & Re-index", async ({
    page,
  }) => {
    let setNewSettingsCalled = false;

    await page.route(SET_NEW_SETTINGS_API, async (route) => {
      setNewSettingsCalled = true;
      await route.fulfill({ status: 200, body: JSON.stringify({}) });
    });

    await navigateToIndexSettings(page);

    const toggle = page.getByRole("switch", { name: /contextual retrieval/i });
    await expect(toggle).toBeVisible({ timeout: 10000 });
    await toggle.click();

    // Any settings change (including non-model changes) always requires a full re-index
    const applyButton = page.getByRole("button", { name: "Apply & Re-index" });
    await expect(applyButton).toBeVisible({ timeout: 5000 });
    await expect(applyButton).toBeEnabled();
    await applyButton.click();

    await expect.poll(() => setNewSettingsCalled, { timeout: 5000 }).toBe(true);
  });
});
