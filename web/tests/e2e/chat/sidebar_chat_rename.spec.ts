// Regression test for renaming a chat from the sidebar popout.
//
// SidebarTab must keep its tree shape stable when its label is swapped for
// the inline rename editor. When the shape changed, React remounted the row
// and the open popover; the remounted popover took focus back from the
// editor, whose blur handler closed it before it could be used.
import { test, expect } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AppSidebarPage } from "@tests/e2e/pages/AppSidebarPage";

const CHAT_NAME = "E2E Rename Target";
const NEW_NAME = "E2E Renamed Chat";

test.describe("Sidebar chat rename", () => {
  let sidebar: AppSidebarPage;
  let chatId: string;

  test.beforeEach(async ({ page }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const apiClient = new OnyxApiClient(page.request);
    chatId = await apiClient.createChatSession(CHAT_NAME);

    sidebar = new AppSidebarPage(page);
    await sidebar.goto();
  });

  test.afterEach(async ({ page }) => {
    const apiClient = new OnyxApiClient(page.request);
    await apiClient.deleteChatSession(chatId);
  });

  test("renames a chat session from the row's options popover", async () => {
    const row = sidebar.chatRow(CHAT_NAME);
    await row.startRename();

    // The editor must appear, hold focus, and start from the current name.
    await expect(row.renameInput).toBeVisible();
    await expect(row.renameInput).toBeFocused();
    await expect(row.renameInput).toHaveValue(CHAT_NAME);

    await row.submitRename(NEW_NAME);

    await expect(sidebar.chatRow(NEW_NAME).root).toBeVisible();
    await expect(row.renameInput).toBeHidden();

    // The new name survives a reload.
    await sidebar.goto();
    await expect(sidebar.chatRow(NEW_NAME).root).toBeVisible();
  });
});
