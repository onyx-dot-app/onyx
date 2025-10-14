import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser, loginAs } from "../utils/auth";
import {
  sendMessage,
  verifyCurrentModel,
  switchModel,
  startNewChat,
} from "../utils/chatActions";
import { ensureImageGenerationEnabled } from "../utils/assistantUtils";

// fails in CI, works locally
// test won't be relevant soon as we'll have a default assistant
// TODO (chris): remove this test when we have a default assistant
test("LLM Ordering and Model Switching", async ({ page }) => {
  // Setup: Clear cookies and log in as a random user
  await page.context().clearCookies();
  await loginAsRandomUser(page);

  // Navigate to the chat page and verify URL
  await page.goto("http://localhost:3000/chat");
  await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 10000 });
  await expect(page.url()).toBe("http://localhost:3000/chat");

  // Configure user settings: Set default model to o3 Mini
  await page.locator("#onyx-user-dropdown").click();
  await page.getByTestId("Settings/user-settings").click();
  await page.getByRole("combobox").nth(1).click();
  await page.getByLabel("GPT 5", { exact: true }).click();
  // Click outside the modal at the very bottom right of the viewport
  const { width, height } = page.viewportSize()!;
  await page.mouse.click(width - 1, height - 1);
  await page.waitForTimeout(5000);
  await verifyCurrentModel(page, "GPT 5");

  // Test model switching within a chat
  await switchModel(page, "GPT 4o Mini");
  await sendMessage(page, "Sample message");
  await verifyCurrentModel(page, "GPT 4o Mini");

  // Create a custom assistant with a specific model
  await page.getByTestId("AppSidebar/more-agents").click();
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.waitForTimeout(2000);
  await page.getByTestId("name").fill("Sample Name");
  await page.getByTestId("description").fill("Sample Description");
  await page.getByTestId("system_prompt").fill("Sample Instructions");
  await page
    .locator('button[role="combobox"] > span:has-text("User Default")')
    .click();
  await page.getByLabel("GPT 4o Mini").getByText("GPT 4o Mini").click();
  await page.getByRole("button", { name: "Create" }).click();

  // Verify custom assistant uses its specified model
  await page.locator("#onyx-chat-input-textarea").fill("");
  await verifyCurrentModel(page, "GPT 4o Mini");

  // Ensure model persistence for custom assistant
  await sendMessage(page, "Sample message");
  await verifyCurrentModel(page, "GPT 4o Mini");

  // Switch back to Default Assistant and verify its model
  await startNewChat(page);
  await verifyCurrentModel(page, "GPT 5");
});

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

  const testModelDisplayName = "GPT 4o Mini";

  // Open the LLM popover by clicking the model selector button
  const llmPopoverTrigger = page.locator('[data-testid="llm-popover-trigger"]');
  await llmPopoverTrigger.click();

  // Wait for the popover to open
  await page.waitForSelector('[role="dialog"]', { timeout: 5000 });

  // Verify that the non-vision model appears in the list
  // The model name is displayed via getDisplayNameForModel, so we search for text containing the model name
  // Use .first() since there might be multiple providers with the same model
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
