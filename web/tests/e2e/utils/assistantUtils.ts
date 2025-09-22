import { Page } from "@playwright/test";
import { expect } from "@chromatic-com/playwright";

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
    await page.goto("http://localhost:3000/chat");
  }

  // Open Assistants modal/list
  await page.getByRole("button", { name: "Explore Assistants" }).click();
  await page.getByRole("button", { name: "Create", exact: true }).click();

  // Fill required fields
  await page.getByTestId("name").fill(name);
  if (description) {
    await page.getByTestId("description").fill(description);
  }
  await page.getByTestId("system_prompt").fill(instructions);

  // Submit create
  await page.getByRole("button", { name: "Create" }).click();

  // Verify it is selected in chat (placeholder contains assistant name)
  await expect(
    page.getByPlaceholder(`How can ${name} help you today`)
  ).toBeVisible({ timeout: 10000 });
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
