import { test } from "@playwright/test";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { TEST_ADMIN_CREDENTIALS } from "@tests/e2e/constants";
import { AdminUsagePage } from "@tests/e2e/pages/AdminUsagePage";

/**
 * Admin per-user usage table. Real e2e (no mocking): the admin sends a chat to
 * accrue usage, then the Usage page must list that usage per user. Requires a
 * working LLM provider in the e2e environment so the chat records token usage.
 */
test.use({ storageState: "admin_auth.json" });

test.describe("admin per-user usage table", () => {
  test("usage shows per user", async ({ page }) => {
    // 1) Accrue usage by sending a chat as the admin.
    const chat = new ChatPage(page);
    await chat.goto();
    await chat.inputBar.fill("hello there");
    await chat.inputBar.send();
    await chat.aiMessage(0).waitFor({ state: "visible", timeout: 60_000 });

    const usage = new AdminUsagePage(page);
    await usage.goto();
    await usage.expectUser(TEST_ADMIN_CREDENTIALS.email);
  });
});
