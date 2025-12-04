import { test, expect } from "@chromatic-com/playwright";
import { loginAs } from "../utils/auth";
import { verifyCurrentModel } from "../utils/chatActions";
import { ensureImageGenerationEnabled } from "../utils/assistantUtils";

test("Non-image-generation model visibility in chat input bar", async ({
  page,
}) => {
  // Setup: Clear cookies and log in as admin
  await page.context().clearCookies();
  await loginAs(page, "admin");

  // Ensure Image Generation is enabled in default assistant
  await ensureImageGenerationEnabled(page);

  // Navigate to the chat page
  await page.goto("http://localhost:3000/chat");
  await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 10000 });

  const testModelDisplayName = "GPT-4o Mini";

  // Open the LLM popover by clicking the model selector button
  const llmPopoverTrigger = page.locator('[data-testid="llm-popover-trigger"]');
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
