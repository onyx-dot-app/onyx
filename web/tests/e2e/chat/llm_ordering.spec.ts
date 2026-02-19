import { test, expect } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { verifyCurrentModel } from "@tests/e2e/utils/chatActions";
import { ensureImageGenerationEnabled } from "@tests/e2e/utils/assistantUtils";
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
    await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 10000 });

    const triggerLocator = page.getByTestId("llm-popover-trigger");
    const currentModelText = (await triggerLocator.textContent())?.trim() ?? "";

    await triggerLocator.click();
    await page.waitForSelector('[role="dialog"]', { timeout: 5000 });

    const dialog = page.locator('[role="dialog"]');
    const allModelItems = dialog.locator("[data-selected]");
    await expect(allModelItems.first()).toBeVisible({ timeout: 5000 });

    const count = await allModelItems.count();
    expect(count).toBeGreaterThan(0);

    // Pick the first model whose name differs from the currently selected one
    let targetItem = allModelItems.first();
    let targetName = "";
    for (let i = 0; i < count; i++) {
      const item = allModelItems.nth(i);
      const text = (await item.textContent())?.trim() ?? "";
      const name = text.split("\n")[0] ?? "";
      if (name && !currentModelText.includes(name)) {
        targetItem = item;
        targetName = name;
        break;
      }
    }

    if (!targetName) {
      targetName =
        ((await targetItem.textContent())?.trim() ?? "").split("\n")[0] ?? "";
    }

    await expect(targetItem).toBeVisible();
    await targetItem.click();

    if (targetName) {
      await verifyCurrentModel(page, targetName);
    }
  });
});
