import { Page } from "@playwright/test";
import { expect } from "@chromatic-com/playwright";

export async function verifyAssistantIsChosen(
  page: Page,
  assistantName: string,
  timeout: number = 5000
) {
  await expect(
    page.getByPlaceholder(`How can ${assistantName} help you today`)
  ).toBeVisible({ timeout });
}

export async function navigateToAssistantInHistorySidebar(
  page: Page,
  testId: string,
  assistantName: string
) {
  await page.getByTestId(`assistant-${testId}`).click();
  try {
    await verifyAssistantIsChosen(page, assistantName);
  } catch (error) {
    console.error("Error in navigateToAssistantInHistorySidebar:", error);
    const pageText = await page.textContent("body");
    console.log("Page text:", pageText);
    throw error;
  }
}

export async function sendMessage(page: Page, message: string) {
  await page.locator("#onyx-chat-input-textarea").click();
  await page.locator("#onyx-chat-input-textarea").fill(message);
  await page.locator("#onyx-chat-input-send-button").click();
  await page.waitForSelector('[data-testid="onyx-ai-message"]');
  // Wait for the copy button to appear, which indicates the message is fully rendered
  await page.waitForSelector('[data-testid="copy-button"]', { timeout: 30000 });

  // Wait for up to 3 seconds for the URL to contain 'chatId='
  await page.waitForFunction(
    () => window.location.href.includes("chatId="),
    null,
    { timeout: 3000 }
  );
}

export async function verifyCurrentModel(page: Page, modelName: string) {
  const chatInput = page.locator("#onyx-chat-input");
  const text = await chatInput.textContent();
  expect(text).toContain(modelName);
}

// Start of Selection
export async function switchModel(page: Page, modelName: string) {
  await page.getByTestId("llm-popover-trigger").click();
  // Target the button inside the popover content specifically
  await page
    .locator('[role="dialog"]')
    .getByRole("button", { name: new RegExp(`${modelName}$`, "i") })
    .click();
}

export async function startNewChat(page: Page) {
  await page.getByRole("link", { name: "New Chat" }).click();
  await expect(page.locator('div[data-testid="chat-intro"]')).toBeVisible();
}
