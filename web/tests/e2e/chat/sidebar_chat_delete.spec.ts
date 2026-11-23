// Deleting the open chat from the sidebar must not leave the user on it.
import { test, expect } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { AppSidebarPage } from "@tests/e2e/pages/AppSidebarPage";

const CHAT_NAME = "E2E Delete Target";
const PROJECT_NAME = "E2E Delete Project";

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

  test.describe("in a project", () => {
    let projectId: number;

    test.beforeEach(async ({ page }) => {
      const apiClient = new OnyxApiClient(page.request);
      projectId = await apiClient.createProject(PROJECT_NAME);
      await apiClient.moveChatSessionToProject(projectId, chatId);
    });

    test.afterEach(async ({ page }) => {
      await new OnyxApiClient(page.request).deleteProject(projectId);
    });

    test("deleting the open chat opens its project", async ({ page }) => {
      const chatPage = new ChatPage(page);
      const sidebar = new AppSidebarPage(page);
      await chatPage.goto(chatId);

      // The sidebar unfolds the open chat's project, so the row is visible.
      const row = sidebar.chatRow(CHAT_NAME);
      await row.delete();

      await expect(page).toHaveURL(`/app?projectId=${projectId}`);
      await expect(row.root).toBeHidden();
    });
  });
});
