import { Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { verifyAssistantIsChosen } from "./chatActions";

export type AssistantParams = {
  name: string;
  description?: string;
  instructions?: string; // system_prompt
};

// Create an assistant via the UI from the app page and wait until it is active
export async function createAssistant(page: Page, params: AssistantParams) {
  const { name, description = "", instructions = "Test Instructions" } = params;

  // Navigate to creation flow
  // We assume we're on /app; if not, go there first
  if (!page.url().includes("/app")) {
    await page.goto("/app");
  }

  // Open Assistants modal/list
  await page.getByTestId("AppSidebar/more-agents").click();
  await page.getByLabel("AgentsPage/new-agent-button").click();

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
 *
 * Navigates to the Chat Preferences page and toggles the Image Generation switch
 * inside the "Actions & Tools" collapsible section (open by default).
 */
export async function ensureImageGenerationEnabled(page: Page): Promise<void> {
  // Navigate to the chat preferences page
  await page.goto("/admin/configuration/chat-preferences");
  await page.waitForLoadState("networkidle");

  // The "Actions & Tools" collapsible is open by default.
  // Find the Image Generation tool switch via its label container.
  const imageGenSwitch = page
    .locator("label")
    .filter({ has: page.getByText("Image Generation", { exact: true }) })
    .locator('button[role="switch"]')
    .first();

  await expect(imageGenSwitch).toBeVisible({ timeout: 10000 });

  // Check if it's already enabled
  const currentState = await imageGenSwitch.getAttribute("aria-checked");

  if (currentState !== "true") {
    // Toggle it on — auto-saves immediately via PATCH /api/admin/default-assistant
    await imageGenSwitch.click();

    // Wait for the auto-save toast to confirm success
    await expect(page.getByText("Tools updated").first()).toBeVisible({
      timeout: 5000,
    });

    // Verify it's now enabled
    const newState = await imageGenSwitch.getAttribute("aria-checked");
    if (newState !== "true") {
      throw new Error("Failed to enable Image Generation tool");
    }
  }
}
