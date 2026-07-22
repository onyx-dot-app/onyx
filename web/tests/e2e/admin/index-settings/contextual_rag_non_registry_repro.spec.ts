/** Regression for https://github.com/onyx-dot-app/onyx/issues/12850 */
import { expect, test } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const SET_NEW_SETTINGS_API = "**/api/search-settings/set-new-search-settings**";
const TEST_EMBEDDING_API = "**/api/admin/embedding/test-embedding";

test.describe("Issue #12850 contextual RAG submit @exclusive", () => {
  test("changing Contextual RAG LLM submits for non-registry LiteLLM embedding model", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const client = new OnyxApiClient(page.request);
    await client.ensurePublicProvider();

    const providersRes = await page.request.get("/api/admin/llm/provider");
    expect(providersRes.ok()).toBeTruthy();
    const { providers } = (await providersRes.json()) as {
      providers: Array<{
        is_public?: boolean;
        model_configurations: Array<{ id: number }>;
      }>;
    };
    const llmProvider =
      providers.find(
        (p) => p.is_public && (p.model_configurations?.length ?? 0) > 0
      ) ?? providers.find((p) => (p.model_configurations?.length ?? 0) > 0);
    expect(llmProvider).toBeTruthy();
    const modelConfigs = llmProvider!.model_configurations;
    expect(modelConfigs.length).toBeGreaterThan(0);

    const firstModelId = modelConfigs[0]!.id!;
    await page.route(TEST_EMBEDDING_API, async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({}) });
    });

    const providerSave = await page.request.put(
      "/api/admin/embedding/embedding-provider",
      {
        data: {
          provider_type: "litellm",
          api_key: "sk-test-key",
          api_url: "https://proxy.example.com",
          api_version: null,
          deployment_name: null,
          is_default_provider: false,
          is_configured: true,
        },
      }
    );
    expect(
      providerSave.ok(),
      `provider save failed: ${providerSave.status()} ${await providerSave.text()}`
    ).toBeTruthy();

    const seedResponse = await page.request.post(
      "/api/search-settings/set-new-search-settings",
      {
        data: {
          model_name: "my-litellm-embed-model",
          model_dim: 1024,
          normalize: false,
          query_prefix: "",
          passage_prefix: "",
          provider_type: "litellm",
          index_name: null,
          multipass_indexing: false,
          enable_contextual_rag: true,
          contextual_rag_model_configuration_id: firstModelId,
          switchover_type: "reindex",
        },
      }
    );
    expect(
      seedResponse.ok(),
      `seed failed: ${seedResponse.status()} ${await seedResponse.text()}`
    ).toBeTruthy();

    await page.goto("/admin/configuration/index-settings");
    await page.waitForLoadState("networkidle");
    await expect(page.getByLabel("admin-page-title")).toHaveText(
      /index settings/i
    );

    await expect(
      page.getByText("my-litellm-embed-model", { exact: false })
    ).toBeVisible({ timeout: 10000 });

    const contextualSwitch = page.getByRole("switch", {
      name: /contextual retrieval/i,
    });
    await expect(contextualSwitch).toBeChecked();

    const contextualModelTrigger = page
      .locator('[data-testid="llm-popover-trigger"]')
      .first();
    await contextualModelTrigger.click();
    const dialog = page.locator('[role="dialog"]').first();
    await expect(dialog).toBeVisible({ timeout: 10000 });
    const modelOptions = dialog.getByRole("button");
    const optionCount = await modelOptions.count();
    expect(optionCount).toBeGreaterThan(0);
    await modelOptions.nth(Math.min(1, optionCount - 1)).click();
    await expect(dialog).not.toBeVisible({ timeout: 5000 });
    const bodyPromise = new Promise<Record<string, unknown>>((resolve) => {
      void page.route(SET_NEW_SETTINGS_API, async (route) => {
        resolve(
          JSON.parse(route.request().postData() ?? "{}") as Record<
            string,
            unknown
          >
        );
        await route.fulfill({ status: 200, body: JSON.stringify({ id: 1 }) });
      });
    });

    const applyButton = page.getByRole("button", { name: "Apply & Re-index" });
    await expect(applyButton).toBeVisible({ timeout: 10000 });
    await applyButton.click();

    await expect(
      page.getByText("Could not find the selected model")
    ).not.toBeVisible({ timeout: 3000 });

    await expect(page.getByText("Re-indexing started")).toBeVisible({
      timeout: 5000,
    });

    const body = await bodyPromise;
    expect(body.model_name).toBe("my-litellm-embed-model");
    expect(body.provider_type).toBe("litellm");
    expect(body.enable_contextual_rag).toBe(true);
  });
});
