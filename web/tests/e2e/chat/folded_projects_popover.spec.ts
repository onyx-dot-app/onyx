import { test, expect } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AppSidebarPage } from "@tests/e2e/pages/AppSidebarPage";

const ALPHA_PROJECT = "E2E Popover Alpha";
const BETA_PROJECT = "E2E Popover Beta";
const ALPHA_ONBOARDING_CHAT = "Alpha onboarding notes";
const ALPHA_RELEASE_CHAT = "Alpha release plan";
const BETA_CHAT = "Beta retrospective";

test.describe("Folded sidebar Projects popover", () => {
  let sidebar: AppSidebarPage;
  let projectIds: number[] = [];
  let chatIds: string[] = [];

  test.beforeEach(async ({ page }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const apiClient = new OnyxApiClient(page.request);
    const alphaId = await apiClient.createProject(ALPHA_PROJECT);
    const betaId = await apiClient.createProject(BETA_PROJECT);
    projectIds = [alphaId, betaId];

    chatIds = [];
    const seedChats = [
      [alphaId, ALPHA_ONBOARDING_CHAT],
      [alphaId, ALPHA_RELEASE_CHAT],
      [betaId, BETA_CHAT],
    ] as const;
    for (const [projectId, chatName] of seedChats) {
      const chatId = await apiClient.createChatSession(chatName);
      await apiClient.moveChatSessionToProject(projectId, chatId);
      chatIds.push(chatId);
    }

    sidebar = new AppSidebarPage(page);
    await sidebar.goto();
    await sidebar.fold();
  });

  test.afterEach(async ({ page }) => {
    const apiClient = new OnyxApiClient(page.request);
    for (const chatId of chatIds) {
      await apiClient.deleteChatSession(chatId);
    }
    for (const projectId of projectIds) {
      await apiClient.deleteProject(projectId);
    }
  });

  test("shows a Projects tab instead of a New Project tab when folded", async () => {
    await expect(sidebar.projectsPopover.trigger).toBeVisible();
    await expect(sidebar.newProjectTab).toBeHidden();
  });

  test("opens a popover listing every project and keeps the tab selected", async () => {
    await sidebar.projectsPopover.open();

    await sidebar.projectsPopover.expectTriggerSelected();
    await expect(sidebar.projectsPopover.searchField).toBeVisible();
    await expect(sidebar.projectsPopover.newProjectButton).toBeVisible();
    await expect(
      sidebar.projectsPopover.projectRow(ALPHA_PROJECT)
    ).toBeVisible();
    await expect(
      sidebar.projectsPopover.projectRow(BETA_PROJECT)
    ).toBeVisible();
  });

  test("expands the owning project when a chat name matches, and restores the full list when cleared", async () => {
    await sidebar.projectsPopover.open();
    await sidebar.projectsPopover.search("onboarding");

    await expect(sidebar.projectsPopover.projectRows).toHaveCount(1);
    await expect(
      sidebar.projectsPopover.chatRow(ALPHA_PROJECT, ALPHA_ONBOARDING_CHAT)
    ).toBeVisible();
    await expect(
      sidebar.projectsPopover.chatRow(ALPHA_PROJECT, ALPHA_RELEASE_CHAT)
    ).toBeHidden();

    await sidebar.projectsPopover.clearSearch();

    await expect(sidebar.projectsPopover.projectRows).toHaveCount(2);
    await expect(
      sidebar.projectsPopover.projectRow(BETA_PROJECT)
    ).toBeVisible();
  });

  test("matches project names and keeps their chats folded", async () => {
    await sidebar.projectsPopover.open();
    await sidebar.projectsPopover.search("Beta");

    await expect(sidebar.projectsPopover.projectRows).toHaveCount(1);
    await expect(
      sidebar.projectsPopover.projectRow(BETA_PROJECT)
    ).toBeVisible();
    await expect(
      sidebar.projectsPopover.chatRow(BETA_PROJECT, BETA_CHAT)
    ).toBeHidden();
  });

  test("stays open when the folder icon toggles a project's chats", async () => {
    await sidebar.projectsPopover.open();
    await expect(
      sidebar.projectsPopover.chatRow(ALPHA_PROJECT, ALPHA_ONBOARDING_CHAT)
    ).toBeHidden();

    await sidebar.projectsPopover.toggleProjectChats(ALPHA_PROJECT);

    await expect(
      sidebar.projectsPopover.chatRow(ALPHA_PROJECT, ALPHA_ONBOARDING_CHAT)
    ).toBeVisible();
    await sidebar.projectsPopover.expectVisible();
  });

  test("closes and navigates when a chat is selected", async () => {
    await sidebar.projectsPopover.open();
    await sidebar.projectsPopover.toggleProjectChats(ALPHA_PROJECT);

    await sidebar.projectsPopover.openChat(ALPHA_PROJECT, chatIds[0]!);

    await sidebar.projectsPopover.expectHidden();
  });
});
