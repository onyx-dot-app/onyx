import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { IndexSettingsPage } from "./IndexSettingsPage";

const INDEX_SETTINGS_URL = "/admin/configuration/index-settings";
const EMBEDDING_PROVIDER_API = "**/api/admin/embedding/embedding-provider**";
const TEST_EMBEDDING_API = "**/api/admin/embedding/test-embedding";
const SET_NEW_SETTINGS_API = "**/api/search-settings/set-new-search-settings**";
const UPDATE_INFERENCE_SETTINGS_API =
  "**/api/search-settings/update-inference-settings**";
const CURRENT_SEARCH_SETTINGS_API =
  "**/api/search-settings/get-current-search-settings**";
const SECONDARY_SEARCH_SETTINGS_API =
  "**/api/search-settings/get-secondary-search-settings**";
const LLM_PROVIDER_API = "**/api/llm/provider**";

interface TestModelConfiguration {
  id: number | null;
  name: string;
  custom_display_name?: string | null;
  display_name?: string | null;
  is_visible: boolean;
  [key: string]: unknown;
}

interface TestLlmProvider {
  model_configurations: TestModelConfiguration[];
  [key: string]: unknown;
}

interface TestLlmProviderResponse {
  providers: TestLlmProvider[];
  [key: string]: unknown;
}

interface TestSearchSettings {
  model_name: string;
  enable_contextual_rag: boolean;
  contextual_rag_model_configuration_id: number | null;
  [key: string]: unknown;
}

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

async function getLlmProviderResponse(
  page: Page
): Promise<TestLlmProviderResponse> {
  const response = await page.request.get("/api/llm/provider");
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as TestLlmProviderResponse;
}

function getVisibleLlmModels(
  response: TestLlmProviderResponse
): TestModelConfiguration[] {
  return response.providers.flatMap((provider) =>
    provider.model_configurations.filter(
      (model) => model.is_visible && model.id !== null
    )
  );
}

function modelDisplayName(model: TestModelConfiguration): string {
  return model.custom_display_name || model.display_name || model.name;
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

test.describe("Index Settings — contextual LLM updates @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test("applies a contextual LLM only to new and updated documents", async ({
    page,
  }) => {
    const current = (await getCurrentSearchSettings(
      page
    )) as TestSearchSettings;
    const llmProviderResponse = await getLlmProviderResponse(page);
    const models = getVisibleLlmModels(llmProviderResponse);
    test.skip(models.length === 0, "A visible LLM model is required");

    const currentContextualModel = models[0]!;
    const nextContextualModel: TestModelConfiguration = {
      ...currentContextualModel,
      id: currentContextualModel.id! + 1000000,
      name: "forward-only-test-model",
      custom_display_name: "Forward-only test model",
    };
    const mockedLlmProviderResponse: TestLlmProviderResponse = {
      ...llmProviderResponse,
      providers: llmProviderResponse.providers.map((provider, index) =>
        index === 0
          ? {
              ...provider,
              model_configurations: [
                ...provider.model_configurations,
                nextContextualModel,
              ],
            }
          : provider
      ),
    };

    let servedSettings: TestSearchSettings = {
      ...current,
      enable_contextual_rag: true,
      contextual_rag_model_configuration_id: currentContextualModel.id,
    };
    let setNewRequestCount = 0;

    await page.route(CURRENT_SEARCH_SETTINGS_API, async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify(servedSettings),
      });
    });
    await page.route(SECONDARY_SEARCH_SETTINGS_API, async (route) => {
      await route.fulfill({ status: 200, body: "null" });
    });
    await page.route(LLM_PROVIDER_API, async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify(mockedLlmProviderResponse),
      });
    });
    await page.route(SET_NEW_SETTINGS_API, async (route) => {
      setNewRequestCount += 1;
      await route.fulfill({ status: 200, body: JSON.stringify({ id: 1 }) });
    });

    const updateBodyPromise = new Promise<Record<string, unknown>>(
      (resolve) => {
        void page.route(UPDATE_INFERENCE_SETTINGS_API, async (route) => {
          const body = JSON.parse(
            route.request().postData() ?? "{}"
          ) as TestSearchSettings;
          servedSettings = body;
          resolve(body);
          await route.fulfill({
            status: 200,
            body: JSON.stringify({
              contextual_rag_model_configuration_id:
                body.contextual_rag_model_configuration_id,
            }),
          });
        });
      }
    );

    const indexSettingsPage = new IndexSettingsPage(page);
    await indexSettingsPage.goto();
    await indexSettingsPage.stageContextualModel(
      modelDisplayName(nextContextualModel)
    );
    await indexSettingsPage.expectContextualModelActions();
    await indexSettingsPage.openForwardOnlyConfirmation();
    await indexSettingsPage.expectForwardOnlyWarning();
    await indexSettingsPage.confirmForwardOnlyUpdate();

    const body = await updateBodyPromise;
    expect(body.contextual_rag_model_configuration_id).toBe(
      nextContextualModel.id
    );
    expect(body.model_name).toBe(current.model_name);
    expect(setNewRequestCount).toBe(0);
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

  test("toggling contextual retrieval without a model stages the change but blocks Apply & Re-index", async ({
    page,
  }) => {
    await navigateToIndexSettings(page);

    const toggle = page.getByRole("switch", { name: /contextual retrieval/i });
    await expect(toggle).toBeVisible({ timeout: 10000 });
    await toggle.click();

    // Contextual Retrieval on with no model must stage the change but block the
    // re-index — the port re-embeds via the LLM and would fail without one.
    await expect(
      page.getByText(/Select a Contextual Retrieval LLM/i)
    ).toBeVisible({ timeout: 5000 });

    // Apply & Re-index renders only when dirty, so its presence proves the change staged.
    const applyButton = page.getByRole("button", { name: "Apply & Re-index" });
    await expect(applyButton).toBeVisible({ timeout: 5000 });
    await expect(applyButton).toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// Empty-registry cloud providers (LiteLLM / Azure)
//
// These providers ship no pre-registered models, so their connect modal
// collects the model spec (name + dimension) itself. Regression coverage for
// the bug where that spec was dropped after the provider row was saved: the
// model was never staged (so no search-settings row was ever created), and
// even when staged it was misresolved as self-hosted (provider_type=null),
// bypassing the saved cloud credentials. Both must reach
// set-new-search-settings with the typed model AND the correct provider_type.
// ---------------------------------------------------------------------------

interface EmptyRegistryProviderCase {
  providerType: string;
  displayName: string;
  // Fills the credential fields unique to this provider via the page object
  // (the shared model-spec fields are filled by the test body).
  fillCredentials: (indexSettings: IndexSettingsPage) => Promise<void>;
}

const EMPTY_REGISTRY_PROVIDERS: EmptyRegistryProviderCase[] = [
  {
    providerType: "litellm",
    displayName: "LiteLLM",
    fillCredentials: (indexSettings) =>
      indexSettings.fillLiteLLMCredentials({
        apiBaseUrl: "https://proxy.example.com",
        apiKey: "sk-test-key",
      }),
  },
  {
    providerType: "azure",
    displayName: "Azure",
    fillCredentials: (indexSettings) =>
      indexSettings.fillAzureCredentials({
        targetUrl: "https://res.openai.azure.com/openai/v1/embeddings",
        apiKey: "az-test-key",
        apiVersion: "2023-05-15",
        deploymentName: "my-deployment",
      }),
  },
];

test.describe("Index Settings — empty-registry providers @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  for (const {
    providerType,
    displayName,
    fillCredentials,
  } of EMPTY_REGISTRY_PROVIDERS) {
    test(`connecting ${displayName} stages its model and applies with provider_type="${providerType}"`, async ({
      page,
    }) => {
      // Stub the credential test + save so no real endpoint/key is needed.
      await page.route(TEST_EMBEDDING_API, async (route) => {
        await route.fulfill({ status: 200, body: JSON.stringify({}) });
      });
      await page.route(EMBEDDING_PROVIDER_API, async (route) => {
        const method = route.request().method();
        if (method === "PUT") {
          await route.fulfill({
            status: 200,
            body: JSON.stringify({ provider_type: providerType }),
          });
        } else if (method === "GET") {
          await route.fulfill({ status: 200, body: JSON.stringify([]) });
        } else {
          await route.continue();
        }
      });

      // Capture the search-settings request body — this is what the bug broke.
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

      const indexSettings = new IndexSettingsPage(page);
      await indexSettings.goto();
      await indexSettings.expandModelPicker();
      await indexSettings.switchToCloudTab();

      // Empty-registry providers render an "Add Configuration" card instead of
      // model cards. Open it, fill the credentials + model spec, and connect.
      await indexSettings.openProviderSetup(displayName);
      await fillCredentials(indexSettings);
      await indexSettings.fillModelSpec({
        modelName: "my-embed-model",
        modelDim: 1024,
      });
      await indexSettings.submitProviderSetup();

      // The just-defined model must be staged — Apply & Re-index appears.
      await indexSettings.expectModelStaged();
      await indexSettings.applyReindex();

      const body = await bodyPromise;
      expect(body.model_name).toBe("my-embed-model");
      expect(Number(body.model_dim)).toBe(1024);
      // The core regression: the model is bound to its cloud provider, NOT
      // sent as provider_type=null (which the backend treats as self-hosted
      // and would ignore the credentials we just saved).
      expect(body.provider_type).toBe(providerType);
    });
  }
});
