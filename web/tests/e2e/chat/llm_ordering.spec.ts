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
  // Setup: Clear cookies and log in as a random user
  await page.context().clearCookies();
  await loginAsRandomUser(page);

  // Navigate to the chat page and verify URL
  await page.goto("http://localhost:3000/chat");
  await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 10000 });
  await expect(page.url()).toBe("http://localhost:3000/chat");

  // Configure user settings: Set default model to o3 Mini
  await page.locator("#onyx-user-dropdown").click();
  await page.getByText("User Settings").click();
  await page.getByRole("combobox").nth(1).click();
  await page.getByLabel("o3 Mini", { exact: true }).click();
  await page.getByLabel("Close modal").click();
  await page.waitForTimeout(5000);
  await verifyCurrentModel(page, "o3 Mini");
  // Test Art Assistant: Should use its own model (GPT 4o)
  await page.reload();
  await page.waitForSelector("#onyx-chat-input-textarea", { timeout: 10000 });
  await navigateToAssistantInHistorySidebar(
    page,
    "[-3]",
    "Assistant for generating"
  );
  await sendMessage(page, "Sample message");
  await verifyCurrentModel(page, "GPT 4o");

  // Test new chat: Should use Art Assistant's model initially
  await startNewChat(page);
  await expect(page.getByText("Assistant for generating")).toBeVisible();
  await verifyCurrentModel(page, "GPT 4o");

  // Test another new chat: Should use user's default model (o3 Mini)
  await startNewChat(page);
  await verifyCurrentModel(page, "o3 Mini");

  // Test model switching within a chat
  await switchModel(page, "GPT 4o Mini");
  await sendMessage(page, "Sample message");
  await verifyCurrentModel(page, "GPT 4o Mini");

  // Create a custom assistant with a specific model
  await page.getByRole("button", { name: "Explore Assistants" }).click();
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.waitForTimeout(2000);
  await page.getByTestId("name").fill("Sample Name");
  await page.getByTestId("description").fill("Sample Description");
  await page.getByTestId("system_prompt").fill("Sample Instructions");
  await page
    .locator('button[role="combobox"] > span:has-text("User Default")')
    .click();
  await page.getByLabel("o3 Mini").getByText("o3 Mini").click();
  await page.getByRole("button", { name: "Create" }).click();

  // Verify custom assistant uses its specified model
  await page.locator("#onyx-chat-input-textarea").fill("");
  await verifyCurrentModel(page, "o3 Mini");

  // Ensure model persistence for custom assistant
  await sendMessage(page, "Sample message");
  await verifyCurrentModel(page, "o3 Mini");

  // Switch back to Art Assistant and verify its model
  await navigateToAssistantInHistorySidebar(
    page,
    "[-3]",
    "Assistant for generating"
  );
  await verifyCurrentModel(page, "GPT 4o");
});
