import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser } from "../utils/auth";
import {
  navigateToAssistantInHistorySidebar,
  sendMessage,
  verifyCurrentModel,
  switchModel,
  startNewChat,
} from "../utils/chatActions";

test("LLM Ordering and Model Switching", async ({ page }) => {
  test.fail();

  // Setup: Clear cookies and log in as a random user
  await page.context().clearCookies();
  await loginAsRandomUser(page);

  // Navigate to the chat page and verify URL
  await page.goto("http://localhost:3000/chat");
  await page.waitForSelector("#onyx-chat-input-textarea");
  await expect(page.url()).toBe("http://localhost:3000/chat");

  // Configure user settings: Set default model to GPT 4 Turbo
  await page.locator("#onyx-user-dropdown").click();
  await page.getByText("User Settings").click();
  await page.getByRole("combobox").click();
  await page.getByLabel("GPT 4 Turbo", { exact: true }).click();
  await page.getByLabel("Close modal").click();
  await verifyCurrentModel(page, "GPT 4 Turbo");

  // Test Art Assistant: Should use its own model (GPT 4o)
  await navigateToAssistantInHistorySidebar(
    page,
    "[-3]",
    "Assistant for generating"
  );
  await sendMessage(page, "Sample message");
  await verifyCurrentModel(page, "GPT 4o");

  // Verify model persistence for Art Assistant
  await sendMessage(page, "Sample message");

  // Test new chat: Should use Art Assistant's model initially
  await startNewChat(page);
  await expect(page.getByText("Assistant for generating")).toBeVisible();
  await verifyCurrentModel(page, "GPT 4o");

  // Test another new chat: Should use user's default model (GPT 4 Turbo)
  await startNewChat(page);
  await verifyCurrentModel(page, "GPT 4 Turbo");

  // Test model switching within a chat
  await switchModel(page, "O1 Mini");
  await sendMessage(page, "Sample message");
  await verifyCurrentModel(page, "O1 Mini");

  // Create a custom assistant with a specific model
  await page.getByRole("button", { name: "Explore Assistants" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await page.waitForTimeout(2000);
  await page.getByTestId("name").fill("Sample Name");
  await page.getByTestId("description").fill("Sample Description");
  await page.getByTestId("system_prompt").fill("Sample Instructions");
  await page.getByRole("combobox").click();
  await page
    .getByLabel("GPT 4 Turbo (Preview)")
    .getByText("GPT 4 Turbo (Preview)")
    .click();
  await page.getByRole("button", { name: "Create" }).click();

  // Verify custom assistant uses its specified model
  await page.locator("#onyx-chat-input-textarea").fill("");
  await verifyCurrentModel(page, "GPT 4 Turbo (Preview)");

  // Ensure model persistence for custom assistant
  await sendMessage(page, "Sample message");
  await verifyCurrentModel(page, "GPT 4 Turbo (Preview)");

  // Switch back to Art Assistant and verify its model
  await navigateToAssistantInHistorySidebar(
    page,
    "[-3]",
    "Assistant for generating"
  );
  await verifyCurrentModel(page, "GPT 4o");
});
