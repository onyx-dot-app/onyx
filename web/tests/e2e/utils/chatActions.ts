import { Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";

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

/** The model picker row: the "Add Model" button, then one pill per selected model. */
function getModelSelector(page: Page): Locator {
  return page.getByTestId("model-selector");
}

/** One pill per selected model. A pill opens its model's settings pane, not the list. */
export function getModelPills(page: Page): Locator {
  return getModelSelector(page).locator("button:not([aria-label='Add Model'])");
}

export async function verifyCurrentModel(page: Page, modelName: string) {
  await expect(
    getModelPills(page).filter({ hasText: modelName }).first()
  ).toBeVisible();
}

/** Opens the model list from the add button and returns the popover. */
export async function openModelList(page: Page): Promise<Locator> {
  await getModelSelector(page)
    .getByRole("button", { name: "Add Model", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByPlaceholder("Search models...")).toBeVisible({
    timeout: 10000,
  });
  return dialog;
}

export async function closeModelPicker(page: Page): Promise<void> {
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
}

/**
 * Makes a row of the open model list the only selected model. A row click
 * adds its model as the first pill and the list stays open, so this closes
 * the list and then removes the older pills with their x.
 */
export async function chooseModelOption(
  page: Page,
  option: Locator
): Promise<string> {
  const pills = getModelPills(page);
  if ((await option.getAttribute("data-interactive-state")) !== "selected") {
    const before = await pills.count();
    await option.click();
    await expect(pills).toHaveCount(before + 1);
  }
  await closeModelPicker(page);

  // The x is the pill's last icon and renders only while several are selected.
  for (let count = await pills.count(); count > 1; count--) {
    await pills.last().locator(".interactive-foreground-icon").last().click();
    await expect(pills).toHaveCount(count - 1);
  }

  const selectedText = (await pills.first().textContent())?.trim() ?? "";
  if (!selectedText) {
    throw new Error("Failed to read selected model text from model selector");
  }
  return selectedText;
}

export async function selectModelFromInputPopover(
  page: Page,
  preferredModels: string[]
): Promise<string> {
  const currentModelText =
    (await getModelPills(page).first().textContent())?.trim() ?? "";

  const dialog = await openModelList(page);
  const searchInput = dialog.getByPlaceholder("Search models...");

  for (const modelName of preferredModels) {
    await searchInput.fill(modelName);
    const modelOptions = dialog.locator("[data-interactive-state]");
    const nonSelectedOptions = dialog.locator(
      '[data-interactive-state="empty"]'
    );

    if ((await modelOptions.count()) > 0) {
      const candidate =
        (await nonSelectedOptions.count()) > 0
          ? nonSelectedOptions.first()
          : modelOptions.first();
      return chooseModelOption(page, candidate);
    }
  }

  // Reset search so fallback sees all available models.
  await searchInput.fill("");

  const nonSelectedOptions = dialog.locator('[data-interactive-state="empty"]');
  if ((await nonSelectedOptions.count()) > 0) {
    const fallback = nonSelectedOptions.first();
    await expect(fallback).toBeVisible();
    return chooseModelOption(page, fallback);
  }

  await closeModelPicker(page).catch(() => {});

  if (currentModelText) {
    return currentModelText;
  }

  throw new Error("Unable to select a model from input popover");
}

export async function switchModel(page: Page, modelName: string) {
  const dialog = await openModelList(page);
  await dialog.getByPlaceholder("Search models...").fill(modelName);
  const option = dialog
    .locator("[data-interactive-state]")
    .filter({ hasText: modelName })
    .first();
  await chooseModelOption(page, option);
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
