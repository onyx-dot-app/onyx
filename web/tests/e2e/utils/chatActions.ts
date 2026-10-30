import { Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { ChatPage } from "@tests/e2e/chat/ChatPage";

export async function verifyDefaultAgentIsChosen(page: Page) {
  await expect(page.getByTestId("onyx-logo")).toBeVisible({ timeout: 5000 });
}

export async function verifyAgentIsChosen(
  page: Page,
  agentName: string,
  timeout: number = 5000
) {
  await expect(
    page.getByTestId("agent-name-display").getByText(agentName)
  ).toBeVisible({ timeout });
}

export async function navigateToAgentInHistorySidebar(
  page: Page,
  testId: string,
  agentName: string
) {
  await page.getByTestId(`assistant-${testId}`).click();
  try {
    await verifyAgentIsChosen(page, agentName);
  } catch (error) {
    console.error("Error in navigateToAgentInHistorySidebar:", error);
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

  await page.locator("#onyx-chat-input-textbox").click();
  await page.locator("#onyx-chat-input-textbox").fill(message);
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
}

export async function verifyCurrentModel(page: Page, modelName: string) {
  await new ChatPage(page).expectModelPill(modelName);
}

export async function selectModelFromInputPopover(
  page: Page,
  preferredModels: string[]
): Promise<string> {
  const chatPage = new ChatPage(page);
  await chatPage.openModelList();
  const { modelOptions, unselectedModelOptions } = chatPage;

  for (const modelName of preferredModels) {
    await chatPage.modelSearchInput.fill(modelName);
    if ((await modelOptions.count()) > 0) {
      const candidate =
        (await unselectedModelOptions.count()) > 0
          ? unselectedModelOptions.first()
          : modelOptions.first();
      return chatPage.chooseModelOption(candidate);
    }
  }

  // Reset search so fallback sees all available models.
  await chatPage.modelSearchInput.fill("");

  if ((await unselectedModelOptions.count()) > 0) {
    const fallback = unselectedModelOptions.first();
    await expect(fallback).toBeVisible();
    return chatPage.chooseModelOption(fallback);
  }

  await chatPage.closeModelPicker().catch(() => {});
  return chatPage.readModelPillText();
}

export async function switchModel(page: Page, modelName: string) {
  await new ChatPage(page).switchModel(modelName);
}

export async function startNewChat(page: Page) {
  await page.getByTestId("AppSidebar/new-session").click();
  await expect(page.getByTestId("chat-intro")).toBeVisible();
}

/**
 * Mark onboarding as complete by setting a display name, so the onboarding
 * prompt doesn't block subsequent chat interactions. Reloads so the cleared
 * onboarding state takes effect.
 */
export async function ensureOnboardingComplete(page: Page): Promise<void> {
  await page.request
    .patch("/api/user/personalization", { data: { name: "Playwright User" } })
    .catch((error) => {
      // Best-effort, but surface the failure so a broken setup is visible.
      console.warn(`Failed to set display name during onboarding: ${error}`);
    });
  await page.reload();
  await page.waitForLoadState("networkidle");
}
