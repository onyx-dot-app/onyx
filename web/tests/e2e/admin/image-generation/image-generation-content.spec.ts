import { test, expect, Page } from "@playwright/test";
import { AdminImageGenerationPage } from "@tests/e2e/pages/AdminImageGenerationPage";
import { loginAs } from "@tests/e2e/utils/auth";

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
          display_name: "gpt-image-2",
          custom_display_name: null,
          image_provider_id: linkedImageProviderId,
        },
        {
          // A name no catalog knows; it is listed too.
          name: "custom-image-model",
          display_name: "custom-image-model",
          custom_display_name: null,
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
  display_name: "gpt-image-2",
  custom_display_name: null,
  llm_provider_id: LLM_PROVIDER_ID,
  llm_provider_name: "Team OpenAI",
  llm_provider_type: "openai",
  llm_provider_owned: false,
  is_default: true,
};

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

  test("lists every image model under its provider", async ({ page }) => {
    await mockImageGenApis(page);
    const imageGenPage = new AdminImageGenerationPage(page);
    await imageGenPage.goto();

    await expect(imageGenPage.providerTitle("Team OpenAI")).toBeVisible();
    await expect(
      imageGenPage.availableModelCard(LLM_PROVIDER_ID, "gpt-image-2")
    ).toBeVisible();
    await expect(
      imageGenPage.availableModelCard(LLM_PROVIDER_ID, "custom-image-model")
    ).toBeVisible();
  });

  test("connects a provider model in one click without credentials", async ({
    page,
  }) => {
    const { linkBodies } = await mockImageGenApis(page);
    const imageGenPage = new AdminImageGenerationPage(page);
    await imageGenPage.goto();

    const available = imageGenPage.availableModelCard(
      LLM_PROVIDER_ID,
      "gpt-image-2"
    );
    await imageGenPage.connect(available);

    const connected = imageGenPage.modelCard(LLM_PROVIDER_ID, "gpt-image-2");
    await expect(imageGenPage.currentDefaultBadge(connected)).toBeVisible({
      timeout: 10000,
    });
    // The model stays in Add Models and says it is connected.
    await expect(available).toContainText("Connected");
    await expect(imageGenPage.dialog).toHaveCount(0);
    expect(linkBodies).toEqual([
      {
        llm_provider_id: LLM_PROVIDER_ID,
        model_name: "gpt-image-2",
        is_default: true,
      },
    ]);
  });
});
