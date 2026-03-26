import { test, expect, Page, Locator } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";

const IMAGE_GENERATION_URL = "/admin/configuration/image-generation";

const FAKE_CONNECTED_CONFIG = {
  image_provider_id: "openai_dalle_3",
  model_configuration_id: 100,
  model_name: "dall-e-3",
  llm_provider_id: 100,
  llm_provider_name: "openai-dalle3",
  is_default: false,
};

const FAKE_DEFAULT_CONFIG = {
  image_provider_id: "openai_gpt_image_1",
  model_configuration_id: 101,
  model_name: "gpt-image-1",
  llm_provider_id: 101,
  llm_provider_name: "openai-gpt-image-1",
  is_default: true,
};

function getProviderCard(page: Page, providerId: string): Locator {
  return page.getByLabel(`image-gen-provider-${providerId}`, { exact: true });
}

/**
 * Sets up route mocks so the page sees configured providers
 * without needing real API keys.
 */
async function mockImageGenApis(
  page: Page,
  configs: (typeof FAKE_CONNECTED_CONFIG)[]
) {
  await page.route("**/api/admin/image-generation/config", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, json: configs });
    } else {
      await route.continue();
    }
  });

  await page.route(
    "**/api/admin/llm/provider?include_image_gen=true",
    async (route) => {
      await route.fulfill({ status: 200, json: { providers: [] } });
    }
  );
}

test.describe("Image Generation Provider Disconnect", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test("should disconnect a connected (non-default) provider", async ({
    page,
  }) => {
    const configs = [{ ...FAKE_CONNECTED_CONFIG }, { ...FAKE_DEFAULT_CONFIG }];
    await mockImageGenApis(page, configs);

    await page.goto(IMAGE_GENERATION_URL);
    await page.waitForSelector("text=Image Generation Model", {
      timeout: 20000,
    });

    const card = getProviderCard(page, "openai_dalle_3");
    await card.waitFor({ state: "visible", timeout: 10000 });

    // Verify disconnect button exists and is enabled
    const disconnectButton = card.getByRole("button", {
      name: "Disconnect DALL-E 3",
    });
    await expect(disconnectButton).toBeVisible();
    await expect(disconnectButton).toBeEnabled();

    // Mock the DELETE to succeed and update the config list
    await page.route(
      "**/api/admin/image-generation/config/openai_dalle_3",
      async (route) => {
        if (route.request().method() === "DELETE") {
          // Update the GET mock to return only the default config
          await page.unroute("**/api/admin/image-generation/config");
          await page.route(
            "**/api/admin/image-generation/config",
            async (route) => {
              if (route.request().method() === "GET") {
                await route.fulfill({
                  status: 200,
                  json: [{ ...FAKE_DEFAULT_CONFIG }],
                });
              } else {
                await route.continue();
              }
            }
          );
          await route.fulfill({ status: 200, json: {} });
        } else {
          await route.continue();
        }
      }
    );

    // Click disconnect
    await disconnectButton.click();

    // Verify confirmation modal appears
    const confirmDialog = page.getByRole("dialog");
    await expect(confirmDialog).toBeVisible({ timeout: 5000 });
    await expect(confirmDialog).toContainText("Disconnect DALL-E 3");

    // Click Disconnect in the confirmation modal
    const confirmButton = confirmDialog.getByRole("button", {
      name: "Disconnect",
    });
    await confirmButton.click();

    // Verify the card reverts to disconnected state (shows "Connect" button)
    await expect(card.getByRole("button", { name: "Connect" })).toBeVisible({
      timeout: 10000,
    });
  });

  test("should show replacement dropdown when disconnecting default provider with alternatives", async ({
    page,
  }) => {
    const configs = [{ ...FAKE_CONNECTED_CONFIG }, { ...FAKE_DEFAULT_CONFIG }];
    await mockImageGenApis(page, configs);

    await page.goto(IMAGE_GENERATION_URL);
    await page.waitForSelector("text=Image Generation Model", {
      timeout: 20000,
    });

    const defaultCard = getProviderCard(page, "openai_gpt_image_1");
    await defaultCard.waitFor({ state: "visible", timeout: 10000 });

    // The disconnect button should be visible and enabled
    const disconnectButton = defaultCard.getByRole("button", {
      name: "Disconnect GPT Image 1",
    });
    await expect(disconnectButton).toBeVisible();
    await expect(disconnectButton).toBeEnabled();

    await disconnectButton.click();

    const confirmDialog = page.getByRole("dialog");
    await expect(confirmDialog).toBeVisible({ timeout: 5000 });

    // Should show replacement dropdown since there's an alternative
    await expect(confirmDialog.getByText("Choose a replacement")).toBeVisible();

    // Disconnect button should be enabled because first replacement is auto-selected
    const confirmButton = confirmDialog.getByRole("button", {
      name: "Disconnect",
    });
    await expect(confirmButton).toBeEnabled();
  });

  test("should show warning when disconnecting default provider with no alternatives", async ({
    page,
  }) => {
    // Only the default config — no other providers configured
    await mockImageGenApis(page, [{ ...FAKE_DEFAULT_CONFIG }]);

    await page.goto(IMAGE_GENERATION_URL);
    await page.waitForSelector("text=Image Generation Model", {
      timeout: 20000,
    });

    const defaultCard = getProviderCard(page, "openai_gpt_image_1");
    await defaultCard.waitFor({ state: "visible", timeout: 10000 });

    const disconnectButton = defaultCard.getByRole("button", {
      name: "Disconnect GPT Image 1",
    });
    await disconnectButton.click();

    const confirmDialog = page.getByRole("dialog");
    await expect(confirmDialog).toBeVisible({ timeout: 5000 });

    // Should warn that image gen will be disabled
    await expect(
      confirmDialog.getByText("until you configure another model")
    ).toBeVisible();

    // Disconnect button should still be enabled
    const confirmButton = confirmDialog.getByRole("button", {
      name: "Disconnect",
    });
    await expect(confirmButton).toBeEnabled();
  });

  test("should not show disconnect button for unconfigured providers", async ({
    page,
  }) => {
    await mockImageGenApis(page, [{ ...FAKE_DEFAULT_CONFIG }]);

    await page.goto(IMAGE_GENERATION_URL);
    await page.waitForSelector("text=Image Generation Model", {
      timeout: 20000,
    });

    // DALL-E 3 is not configured — should not have a disconnect button
    const card = getProviderCard(page, "openai_dalle_3");
    await card.waitFor({ state: "visible", timeout: 10000 });

    const disconnectButton = card.getByRole("button", {
      name: "Disconnect DALL-E 3",
    });
    await expect(disconnectButton).not.toBeVisible();
  });
});
