// Shared test utilities for tool/action management and greetings

import { Locator, Page } from "@playwright/test";

export const TOOL_IDS = {
  actionToggle: '[data-testid="action-management-toggle"]',
  options: '[data-testid="tool-options"]',
  // Generic toggle selector used inside tool options
  toggleInput: 'input[type="checkbox"], input[type="radio"], [role="switch"]',
} as const;

/**
 * The labels the built-in tools carry in the popover.
 *
 * A row is found by the name it shows, not by a test id: it renders as a
 * `role="button"` labelled by the tool, so the test asks for what the user
 * sees. `DISPLAY_NAME` on the backend tool classes is the source of truth
 * (e.g. `SearchTool.DISPLAY_NAME`).
 */
export const TOOL_NAMES = {
  internalSearch: "Internal Search",
  webSearch: "Web Search",
  imageGeneration: "Image Generation",
} as const;

/**
 * One tool row in the open actions popover.
 *
 * Matched on a substring rather than the exact name: the row is named by its
 * whole subtree, so its trailing action buttons ("Disable", "Configure
 * Connectors") end up in the accessible name too.
 */
export function toolOption(page: Page, name: string): Locator {
  return page.locator(TOOL_IDS.options).getByRole("button", { name });
}

export { GREETING_MESSAGES } from "../../../src/lib/chat/greetingMessages";

// Wait for the unified assistant greeting and return its text
export async function waitForUnifiedGreeting(page: Page): Promise<string> {
  const el = await page.waitForSelector('[data-testid="onyx-logo"]', {
    timeout: 5000,
  });
  const text = (await el.textContent())?.trim() || "";
  return text;
}

// Ensure the Action Management popover is open
export async function openActionManagement(page: Page): Promise<void> {
  // The toggle closes an open popover, so a caller that already has one would
  // shut it by asking for it again.
  if (await page.locator(TOOL_IDS.options).isVisible()) return;

  const actionToggle = page.locator(TOOL_IDS.actionToggle);
  await actionToggle.waitFor();
  await actionToggle.click();
  await page.locator(TOOL_IDS.options).waitFor();
}

// Check presence of the Action Management toggle
export async function isActionTogglePresent(page: Page): Promise<boolean> {
  const el = await page.$(TOOL_IDS.actionToggle);
  return !!el;
}

/**
 * Click the disable/enable (slash) button on a tool line item.
 * The button is hidden until hover; we hover first, then force-click
 * using aria-label which matches the button's current state.
 */
export async function toggleToolDisabled(row: Locator): Promise<void> {
  await row.hover();
  const slashButton = row.locator(
    'button[aria-label="Disable"], button[aria-label="Enable"]'
  );
  await slashButton.first().click({ force: true });
}

/**
 * Open the source management secondary view for the internal search tool.
 * Assumes the ToolsPopover is already open.
 */
export async function openSourceManagement(page: Page): Promise<void> {
  await toolOption(page, TOOL_NAMES.internalSearch)
    .locator('button[aria-label="Configure Connectors"]')
    .click();
  // Wait for the source list Back button (indicates secondary view is open)
  await page.locator('button[aria-label="Back"]').waitFor({ timeout: 5000 });
}

/**
 * Get a source toggle Switch in the source management view by display name.
 */
export function getSourceToggle(page: Page, sourceName: string) {
  return page.locator(`[aria-label="Toggle ${sourceName}"]`);
}
