import { Page } from "@playwright/test";
import { expect } from "@chromatic-com/playwright";
import { verifyAssistantIsChosen } from "./chatActions";

export type AssistantParams = {
  name: string;
  description?: string;
  instructions?: string; // system_prompt
};

// Create an assistant via the UI from the chat page and wait until it is active
export async function createAssistant(page: Page, params: AssistantParams) {
  const { name, description = "", instructions = "Test Instructions" } = params;

  // Navigate to creation flow
  // We assume we're on /chat; if not, go there first
  if (!page.url().includes("/chat")) {
    await page.goto("/chat");
  }

  // Open Assistants modal/list
  await page.getByTestId("AppSidebar/more-agents").click();
  await page.getByTestId("AgentsPage/new-agent-button").click();

  // Fill required fields
  await page.locator('input[name="name"]').fill(name);
  if (description) {
    await page.locator('textarea[name="description"]').fill(description);
  }
  await page.locator('textarea[name="instructions"]').fill(instructions);

  // Submit create
  await page.getByRole("button", { name: "Create" }).click();

  // Verify it is selected in chat (placeholder contains assistant name)
  await verifyAssistantIsChosen(page, name);
}

// Pin an assistant by its visible name in the sidebar list.
// If already pinned, this will leave it pinned (no-op).
export async function pinAssistantByName(
  page: Page,
  assistantName: string
): Promise<void> {
  const row = page
    .locator('[data-testid^="assistant-["]')
    .filter({ hasText: assistantName })
    .first();

  await row.waitFor({ state: "visible", timeout: 10000 });
  await row.hover();

  const button = row.locator("button").first();
  await button.hover();

  // Tooltip indicates pin vs unpin; use it if available
  const pinTooltip = page.getByText("Pin this assistant to the sidebar");
  const unpinTooltip = page.getByText("Unpin this assistant from the sidebar");

  try {
    await expect(pinTooltip.or(unpinTooltip)).toBeVisible({ timeout: 2000 });
  } catch {
    // Tooltip may fail to appear in CI; continue optimistically
  }

  if (await pinTooltip.isVisible().catch(() => false)) {
    await button.click();
    await page.waitForTimeout(300);
  }
}

/**
 * Ensures the Image Generation tool is enabled in the default assistant configuration.
 * If it's not enabled, it will toggle it on.
 */
export async function ensureImageGenerationEnabled(page: Page): Promise<void> {
  // Navigate to the default assistant configuration page
  await page.goto("/admin/configuration/default-assistant");

  // Wait for the page to load
  await page.waitForLoadState("networkidle");

  // Find the Image Generation tool checkbox
  // The tool display name is "Image Generation" based on the description in the code
  // Note: The UI changed from switches to checkboxes
  const checkboxElement = page.getByLabel("image-generation-checkbox").first();

  // Check if it's already enabled
  const isEnabled = Boolean(await checkboxElement.getAttribute("aria-checked"));

  if (!isEnabled) {
    // If not enabled, click to enable it
    await checkboxElement.click();

    // Wait for the toggle to complete
    await page.waitForTimeout(1000);

    // Verify it's now enabled
    const newState = Boolean(
      await checkboxElement.getAttribute("aria-checked")
    );
    if (!newState) throw new Error("Failed to enable Image Generation tool");
  }
}
