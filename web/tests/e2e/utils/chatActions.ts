import { Page } from "@playwright/test";
import { expect } from "@chromatic-com/playwright";

export async function navigateToAssistantInHistorySidebar(
  page: Page,
  testId: string,
  description: string
) {
  await page.getByTestId(`assistant-${testId}`).click();
  try {
    await expect(page.getByText(description)).toBeVisible();
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
  await page.waitForSelector("#onyx-ai-message");
  await page.waitForTimeout(2000);
}

export async function verifyCurrentModel(page: Page, modelName: string) {
  await page.waitForTimeout(1000);
  const chatInput = page.locator("#onyx-chat-input");
  const text = await chatInput.textContent();
  expect(text).toContain(modelName);
  await page.waitForTimeout(1000);
}

// Start of Selection
export async function switchModel(page: Page, modelName: string) {
  await page.getByTestId("llm-popover-trigger").click();
  await page
    .getByRole("button", { name: `Logo ${modelName}`, exact: true })
    .click();
  await page.waitForTimeout(1000);
}

export async function startNewChat(page: Page) {
  await page.getByRole("link", { name: "Start New Chat" }).click();
  await expect(page.locator('div[data-testid="chat-intro"]')).toBeVisible();
}
