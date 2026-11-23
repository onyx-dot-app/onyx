import { test, expect, Page, Locator } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { loginAs } from "@tests/e2e/utils/auth";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";

const IMAGE_GENERATION_URL = ADMIN_ROUTES.IMAGE_GENERATION.path;

const FAKE_CONNECTED_CONFIG = {
  image_provider_id: "openai_gpt_image_1_5",
  model_configuration_id: 100,
  model_name: "gpt-image-1.5",
  display_name: "gpt-image-1.5",
  custom_display_name: null,
  llm_provider_id: 100,
  llm_provider_type: "openai",
  llm_provider_owned: true,
  llm_provider_name: "openai-gpt-image-1-5",
  is_default: false,
};

const FAKE_DEFAULT_CONFIG = {
  image_provider_id: "openai_gpt_image_1",
  model_configuration_id: 101,
  model_name: "gpt-image-1",
  display_name: "gpt-image-1",
  custom_display_name: null,
  llm_provider_id: 101,
  llm_provider_type: "openai",
  llm_provider_owned: true,
  llm_provider_name: "openai-gpt-image-1",
  is_default: true,
};

function getProviderCard(page: Page, providerId: string): Locator {
  return page.getByLabel(`image-gen-provider-${providerId}`, { exact: true });
}

function mainContainer(page: Page): Locator {
  return page.locator("[data-main-container]");
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
    "**/api/admin/image-generation/llm-providers",
    async (route) => {
      await route.fulfill({
        status: 200,
        json: [
          {
            llm_provider_id: 5,
            llm_provider_name: "Team OpenAI",
            provider: "openai",
            is_public: true,
            models: [
              {
                name: "gpt-image-2",
                display_name: "gpt-image-2",
                custom_display_name: null,
                is_recommended: true,
                image_provider_id: null,
              },
            ],
          },
        ],
      });
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
    await page.waitForSelector("text=Add Models", {
      timeout: 20000,
    });

    const card = getProviderCard(page, "openai_gpt_image_1_5");
    await card.waitFor({ state: "visible", timeout: 10000 });

    await expectElementScreenshot(mainContainer(page), {
      name: "image-gen-disconnect-non-default-before",
    });

    // Disconnect button is always visible
    await card.hover();
    const disconnectButton = card.getByRole("button", {
      name: "Disconnect GPT Image 1.5",
    });
    await expect(disconnectButton).toBeVisible();
    await expect(disconnectButton).toBeEnabled();

    // Mock the DELETE to succeed and update the config list
    await page.route(
      "**/api/admin/image-generation/config/openai_gpt_image_1_5",
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

    // A non-default model disconnects at once, with no confirmation
    await disconnectButton.click();
    await expect(page.getByRole("dialog")).toHaveCount(0);

    // Legacy cards show only while connected
    await expect(card).toHaveCount(0, { timeout: 10000 });

    await expectElementScreenshot(mainContainer(page), {
      name: "image-gen-disconnect-non-default-after",
    });
  });

  test("should disconnect the default provider with no confirmation", async ({
    page,
  }) => {
    const configs = [{ ...FAKE_CONNECTED_CONFIG }, { ...FAKE_DEFAULT_CONFIG }];
    await mockImageGenApis(page, configs);
    await page.route(
      "**/api/admin/image-generation/config/openai_gpt_image_1",
      async (route) => {
        if (route.request().method() === "DELETE") {
          await route.fulfill({ status: 200, json: {} });
        } else {
          await route.continue();
        }
      }
    );

    await page.goto(IMAGE_GENERATION_URL);
    await page.waitForSelector("text=Add Models", {
      timeout: 20000,
    });

    const defaultCard = getProviderCard(page, "openai_gpt_image_1");
    await defaultCard.waitFor({ state: "visible", timeout: 10000 });

    await defaultCard.hover();
    const deleteRequest = page.waitForRequest(
      (request) =>
        request.method() === "DELETE" &&
        request.url().endsWith("/image-generation/config/openai_gpt_image_1")
    );
    await defaultCard
      .getByRole("button", { name: "Disconnect GPT Image 1" })
      .click();

    // The default disconnects at once too; no replacement is asked for.
    await deleteRequest;
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  test("should not show disconnect button for unconfigured providers", async ({
    page,
  }) => {
    await mockImageGenApis(page, [{ ...FAKE_DEFAULT_CONFIG }]);

    await page.goto(IMAGE_GENERATION_URL);
    await page.waitForSelector("text=Add Models", {
      timeout: 20000,
    });

    // gpt-image-2 on the LLM provider is not connected — no disconnect button
    const card = page.getByLabel("image-gen-model-5-gpt-image-2", {
      exact: true,
    });
    await card.waitFor({ state: "visible", timeout: 10000 });

    const disconnectButton = card.getByRole("button", {
      name: "Disconnect gpt-image-2",
    });
    await expect(disconnectButton).not.toBeVisible();

    await expectElementScreenshot(mainContainer(page), {
      name: "image-gen-disconnect-unconfigured",
    });
  });
});
