import { test, expect } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import {
  chooseModelOption,
  getModelPills,
  openModelList,
} from "@tests/e2e/utils/chatActions";
import { ensureImageGenerationEnabled } from "@tests/e2e/utils/agentUtils";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

test.describe("LLM Ordering", () => {
  let imageGenConfigId: string | null = null;

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const apiClient = new OnyxApiClient(page.request);

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
    const apiClient = new OnyxApiClient(page.request);

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
    await ensureImageGenerationEnabled(page);

    await page.goto("/app");
    await page.waitForSelector("#onyx-chat-input-textbox", { timeout: 10000 });

    const originalModelText =
      (await getModelPills(page).first().textContent())?.trim() ?? "";

    const dialog = await openModelList(page);
    const allModelItems = dialog.locator("[data-interactive-state]");
    await expect(allModelItems.first()).toBeVisible({ timeout: 5000 });

    const count = await allModelItems.count();
    expect(count).toBeGreaterThan(0);

    // Pick the first non-selected model so the pill text changes after the switch
    const nonSelectedItem = dialog
      .locator('[data-interactive-state="empty"]')
      .first();
    const hasNonSelected = (await nonSelectedItem.count()) > 0;
    const targetItem = hasNonSelected ? nonSelectedItem : allModelItems.first();

    await expect(targetItem).toBeVisible();
    const selectedModelText = await chooseModelOption(page, targetItem);

    // Verify the popover closed and the sole pill shows the new model
    await expect(dialog).toBeHidden();
    await expect(getModelPills(page)).toHaveCount(1);

    if (hasNonSelected) {
      expect(selectedModelText).not.toBe(originalModelText);
    }
  });
});
