import { Page } from "@playwright/test";
import { expect } from "@playwright/test";

export async function verifyDefaultAssistantIsChosen(page: Page) {
  await expect(page.getByTestId("onyx-logo")).toBeVisible({ timeout: 5000 });
}

export async function verifyAssistantIsChosen(
  page: Page,
  assistantName: string,
  timeout: number = 5000
) {
  await expect(
    page.getByTestId("assistant-name-display").getByText(assistantName)
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
  // Count existing AI messages before sending
  const existingMessageCount = await page
    .locator('[data-testid="onyx-ai-message"]')
    .count();

  await page.locator("#onyx-chat-input-textarea").click();
  await page.locator("#onyx-chat-input-textarea").fill(message);
  await page.locator("#onyx-chat-input-send-button").click();

  // Wait for a NEW AI message to appear (count should increase)
  await expect(page.locator('[data-testid="onyx-ai-message"]')).toHaveCount(
    existingMessageCount + 1,
    { timeout: 30000 }
  );

  // Wait for up to 10 seconds for the URL to contain 'chatId='
  await page.waitForFunction(
    () => window.location.href.includes("chatId="),
    null,
    { timeout: 10000 }
  );

  // wait for stream to complete
  await page.waitForLoadState("networkidle");
}

export async function verifyCurrentModel(page: Page, modelName: string) {
  const text = await page
    .getByTestId("ChatInputBar/llm-popover-trigger")
    .textContent();
  expect(text).toContain(modelName);
}

export async function switchModel(page: Page, modelName: string) {
  await page.getByTestId("ChatInputBar/llm-popover-trigger").click();

  // Wait for the popover to open
  await page.waitForSelector('[role="dialog"]', { state: "visible" });

  // LineItem is a <button> element inside the popover
  // Find the button that contains the model name
  const modelButton = page
    .locator('[role="dialog"]')
    .locator("button")
    .filter({ hasText: modelName })
    .first();

  await modelButton.click();

  // Wait for the popover to close
  await page.waitForSelector('[role="dialog"]', { state: "hidden" });
}

export async function startNewChat(page: Page) {
  await page.getByTestId("AppSidebar/new-session").click();
  await expect(page.getByTestId("chat-intro")).toBeVisible();
}
