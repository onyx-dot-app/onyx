import { test, expect } from "@chromatic-com/playwright";
import { loginAs } from "../utils/auth";
import { verifyCurrentModel } from "../utils/chatActions";
import { ensureImageGenerationEnabled } from "../utils/assistantUtils";
import { OnyxApiClient } from "../utils/onyxApiClient";

test.describe("LLM Ordering", () => {
  let imageGenConfigId: string | null = null;

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const apiClient = new OnyxApiClient(page);

    // Create image generation config so the checkbox appears
    try {
      imageGenConfigId = await apiClient.createImageGenerationConfig(
        `test-image-gen-${Date.now()}`
      );
    } catch (error) {
      console.warn(`Failed to create image generation config: ${error}`);
    }
  });

  test.afterEach(async ({ page }) => {
    const apiClient = new OnyxApiClient(page);

    if (imageGenConfigId !== null) {
      try {
        await apiClient.deleteImageGenerationConfig(imageGenConfigId);
        imageGenConfigId = null;
      } catch (error) {
        console.warn(`Failed to delete image gen config: ${error}`);
      }
    }
  });

  test("Non-image-generation model visibility in chat input bar", async ({
    page,
  }) => {
    // Ensure Image Generation is enabled in default assistant
    await ensureImageGenerationEnabled(page);

    // Navigate to the chat page
    await page.goto("/chat");
    await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 10000 });

    const testModelDisplayName = "GPT-4o Mini";

    // Open the LLM popover by clicking the model selector button
    const llmPopoverTrigger = page.locator(
      '[data-testid="llm-popover-trigger"]'
    );
    await llmPopoverTrigger.click();

    // Wait for the popover to open
    await page.waitForSelector('[role="dialog"]', { timeout: 5000 });

    // Verify that the non-vision model appears in the list
    // The model name is displayed via getDisplayNameForModel
    const modelButton = page
      .locator('[role="dialog"]')
      .locator("button")
      .filter({ hasText: testModelDisplayName })
      .first();

    await expect(modelButton).toBeVisible();

    // Optionally, select the model to verify it works
    await modelButton.click();
    await verifyCurrentModel(page, testModelDisplayName);
  });
});
