// Shared test utilities for tool/action management and greetings

import { Page } from "@playwright/test";

export const TOOL_IDS = {
  actionToggle: '[data-testid="action-management-toggle"]',
  options: '[data-testid="tool-options"]',
  // These IDs are derived from tool.name in the app
  searchOption: '[data-testid="tool-option-SearchTool"]',
  webSearchOption: '[data-testid="tool-option-WebSearchTool"]',
  imageGenerationOption: '[data-testid="tool-option-ImageGenerationTool"]',
  // Generic toggle selector used inside tool options
  toggleInput: 'input[type="checkbox"], input[type="radio"], [role="switch"]',
} as const;

export { GREETING_MESSAGES } from "../../../src/lib/chat/greetingMessages";

// Wait for the unified assistant greeting and return its text
export async function waitForUnifiedGreeting(page: Page): Promise<string> {
  const el = await page.waitForSelector('[data-testid="greeting-message"]', {
    timeout: 5000,
  });
  const text = (await el.textContent())?.trim() || "";
  return text;
}

// Ensure the Action Management popover is open
export async function openActionManagement(page: Page): Promise<void> {
  await page.click(TOOL_IDS.actionToggle);
  await page.waitForSelector(TOOL_IDS.options, { timeout: 5000 });
}

// Check presence of the Action Management toggle
export async function isActionTogglePresent(page: Page): Promise<boolean> {
  const el = await page.$(TOOL_IDS.actionToggle);
  return !!el;
}
