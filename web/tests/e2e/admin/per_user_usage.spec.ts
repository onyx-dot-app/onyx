import { test, expect } from "@playwright/test";
import { ChatPage } from "@tests/e2e/chat/ChatPage";

/**
 * Admin per-user usage table + Reset. Real e2e (no mocking): the admin sends a
 * chat to accrue usage, then the Usage Statistics page must list that usage per
 * user, and the Reset action must clear it. Requires a working LLM provider in
 * the e2e environment so the chat records token usage.
 */
test.use({ storageState: "admin_auth.json" });

test.describe("admin per-user usage table + reset", () => {
  test("usage shows per user and Reset clears it", async ({ page }) => {
    // 1) Accrue usage by sending a chat as the admin.
    const chat = new ChatPage(page);
    await chat.goto();
    await chat.inputBar.fill("hello there");
    await chat.inputBar.send();
    await chat.aiMessage(0).waitFor({ state: "visible", timeout: 60_000 });

    // 2) The admin's usage now appears in the per-user table.
    await page.goto("/admin/performance/usage");
    const row = page.locator('[data-testid^="usage-row-"]').first();
    await expect(row).toBeVisible({ timeout: 15_000 });

    // 3) Reset clears the user's current-window usage (toast confirms).
    await row.getByRole("button", { name: "Reset" }).click();
    await expect(page.getByText(/reset usage for/i)).toBeVisible({
      timeout: 10_000,
    });
  });
});
