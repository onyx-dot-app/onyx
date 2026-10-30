import { test, expect, Page, Locator } from "@playwright/test";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { loginAs } from "@tests/e2e/utils/auth";

const IMAGE_GENERATION_URL = `http://localhost:3000${ADMIN_ROUTES.IMAGE_GENERATION.path}`;

const LLM_PROVIDER_ID = 7;
const LINKED_IMAGE_PROVIDER_ID = `llm-${LLM_PROVIDER_ID}-gpt-image-2`;

function llmProviders(linkedImageProviderId: string | null) {
  return [
    {
      llm_provider_id: LLM_PROVIDER_ID,
      llm_provider_name: "Team OpenAI",
      provider: "openai",
      is_public: true,
      models: [
        {
          name: "gpt-image-2",
          display_name: null,
          is_recommended: true,
          image_provider_id: linkedImageProviderId,
        },
        {
          name: "gpt-5",
          display_name: null,
          is_recommended: false,
          image_provider_id: null,
        },
      ],
    },
  ];
}

const LINKED_CONFIG = {
  image_provider_id: LINKED_IMAGE_PROVIDER_ID,
  model_configuration_id: 300,
  model_name: "gpt-image-2",
  llm_provider_id: LLM_PROVIDER_ID,
  llm_provider_name: "Team OpenAI",
  llm_provider_type: "openai",
  llm_provider_owned: false,
  is_default: true,
};

function getModelCard(page: Page, modelName: string): Locator {
  return page.getByLabel(`image-gen-model-${LLM_PROVIDER_ID}-${modelName}`, {
    exact: true,
  });
}

async function mockImageGenApis(
  page: Page
): Promise<{ linkBodies: unknown[] }> {
  let linked = false;
  const linkBodies: unknown[] = [];
  await page.route("**/api/admin/image-generation/config", async (route) => {
    await route.fulfill({ status: 200, json: linked ? [LINKED_CONFIG] : [] });
  });
  await page.route(
    "**/api/admin/image-generation/llm-providers",
    async (route) => {
      await route.fulfill({
        status: 200,
        json: llmProviders(linked ? LINKED_IMAGE_PROVIDER_ID : null),
      });
    }
  );
  await page.route(
    "**/api/admin/image-generation/config/link",
    async (route) => {
      linkBodies.push(route.request().postDataJSON());
      linked = true;
      await route.fulfill({ status: 200, json: LINKED_CONFIG });
    }
  );
  return { linkBodies };
}

test.describe("Image Generation models from LLM providers", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test("recommended filter hides non-image models until turned off", async ({
    page,
  }) => {
    await mockImageGenApis(page);
    await page.goto(IMAGE_GENERATION_URL);
    await page.waitForSelector("text=Image Generation Model", {
      timeout: 20000,
    });

    await expect(page.getByText("Team OpenAI", { exact: true })).toBeVisible();
    await expect(getModelCard(page, "gpt-image-2")).toBeVisible();
    await expect(getModelCard(page, "gpt-5")).toHaveCount(0);

    await page
      .getByRole("switch", { name: "Recommended image models only" })
      .click();
    await expect(getModelCard(page, "gpt-5")).toBeVisible();
  });

  test("connects a provider model in one click without credentials", async ({
    page,
  }) => {
    const { linkBodies } = await mockImageGenApis(page);
    await page.goto(IMAGE_GENERATION_URL);
    await page.waitForSelector("text=Image Generation Model", {
      timeout: 20000,
    });

    const card = getModelCard(page, "gpt-image-2");
    await card.getByRole("button", { name: "Connect" }).click();

    await expect(
      card.getByRole("button", { name: "Current Default" })
    ).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(linkBodies).toEqual([
      {
        llm_provider_id: LLM_PROVIDER_ID,
        model_name: "gpt-image-2",
        is_default: true,
      },
    ]);
  });
});
