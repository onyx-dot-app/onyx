// Deleting the open chat from the sidebar must not leave the user on it.
import { test, expect } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { AppSidebarPage } from "@tests/e2e/pages/AppSidebarPage";

const CHAT_NAME = "E2E Delete Target";

test.describe("Sidebar chat delete", () => {
  let chatId: string;

  test.beforeEach(async ({ page }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    chatId = await new OnyxApiClient(page.request).createChatSession(CHAT_NAME);
  });

  test.afterEach(async ({ page }) => {
    // Soft: the test deletes the chat when it passes.
    await new OnyxApiClient(page.request).deleteChatSession(chatId);
  });

  test("deleting the open chat opens a new session", async ({ page }) => {
    const chatPage = new ChatPage(page);
    const sidebar = new AppSidebarPage(page);
    await chatPage.goto(chatId);

    const row = sidebar.chatRow(CHAT_NAME);
    await row.delete();

    await expect(page).toHaveURL("/app");
    await expect(row.root).toBeHidden();
  });
});
