import { test, expect, Page, Locator } from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { loginAs } from "@tests/e2e/utils/auth";
import { expectScreenshot } from "@tests/e2e/utils/visualRegression";

// Test data storage
const TEST_PREFIX = "E2E-CMD";
let chatSessionIds: string[] = [];
let projectIds: number[] = [];

/**
 * Helper to get the command menu dialog locator (using the content wrapper)
 */
function getCommandMenuContent(page: Page): Locator {
  return page.locator('[role="dialog"]:has([data-command-menu-list])');
}

/**
 * Helper to open the command menu and return a scoped locator
 */
async function openCommandMenu(page: Page): Promise<Locator> {
  await page.getByLabel("Open chat search").click();
  const dialog = getCommandMenuContent(page);
  await expect(
    dialog.getByPlaceholder("Search chat sessions, projects...")
  ).toBeVisible();
  return dialog;
}

test.describe("Chat Search Command Menu", () => {
  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await loginAs(page, "user");
    const client = new OnyxApiClient(page.request);

    await page.goto("/app");
    await page.waitForLoadState("networkidle");

    for (let i = 1; i <= 5; i++) {
      const id = await client.createChatSession(`${TEST_PREFIX} Chat ${i}`);
      chatSessionIds.push(id);
    }

    for (let i = 1; i <= 4; i++) {
      const id = await client.createProject(`${TEST_PREFIX} Project ${i}`);
      projectIds.push(id);
    }

    await context.close();
  });

  test.afterAll(async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await loginAs(page, "user");
    const client = new OnyxApiClient(page.request);

    await page.goto("/app");
    await page.waitForLoadState("networkidle");

    for (const id of chatSessionIds) {
      await client.deleteChatSession(id);
    }
    for (const id of projectIds) {
      await client.deleteProject(id);
    }

    await context.close();
  });

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "user");
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
  });

  // -- Opening --

  test("Opens with search input, New Session action, and correct positioning", async ({
    page,
  }) => {
    const dialog = await openCommandMenu(page);

    await expect(
      dialog.getByPlaceholder("Search chat sessions, projects...")
    ).toBeFocused();
    await expect(
      dialog.locator('[data-command-item="new-session"]')
    ).toBeVisible();

    await expectScreenshot(page, { name: "command-menu-default-open" });
  });

  // -- Preview limits --

  test("Shows at most 4 chats and 3 projects in preview", async ({ page }) => {
    const dialog = await openCommandMenu(page);

    const chatCount = await dialog
      .locator('[data-command-item^="chat-"]')
      .count();
    expect(chatCount).toBeLessThanOrEqual(4);

    const projectCount = await dialog
      .locator('[data-command-item^="project-"]')
      .count();
    expect(projectCount).toBeLessThanOrEqual(3);
  });

  test('Shows "Recent Sessions", "Projects" filters and "New Project" action', async ({
    page,
  }) => {
    const dialog = await openCommandMenu(page);

    await expect(
      dialog.locator('[data-command-item="recent-sessions"]')
    ).toBeVisible();
    await expect(
      dialog.locator('[data-command-item="projects"]')
    ).toBeVisible();
    await expect(
      dialog.locator('[data-command-item="new-project"]')
    ).toBeVisible();
  });

  // -- Filter expansion --

  test('"Recent Sessions" filter expands to show all 5 chats', async ({
    page,
  }) => {
    const dialog = await openCommandMenu(page);
    await dialog.locator('[data-command-item="recent-sessions"]').click();

    await page.waitForTimeout(500);

    for (let i = 1; i <= 5; i++) {
      await expect(
        dialog.locator(`[data-command-item="chat-${chatSessionIds[i - 1]}"]`)
      ).toBeVisible();
    }

    await expect(dialog.getByText("Sessions")).toBeVisible();

    await expectScreenshot(page, { name: "command-menu-sessions-filter" });
  });

  test('"Projects" filter expands to show all 4 projects', async ({ page }) => {
    const dialog = await openCommandMenu(page);
    await dialog.locator('[data-command-item="projects"]').click();

    await page.waitForTimeout(500);

    for (let i = 1; i <= 4; i++) {
      await expect(
        dialog.locator(`[data-command-item="project-${projectIds[i - 1]}"]`)
      ).toBeVisible();
    }

    await expectScreenshot(page, { name: "command-menu-projects-filter" });
  });

  test("Filter chip X removes filter and returns to all", async ({ page }) => {
    const dialog = await openCommandMenu(page);
    await dialog.locator('[data-command-item="recent-sessions"]').click();
    await expect(dialog.getByText("Sessions")).toBeVisible();

    await dialog.locator('button[aria-label="Remove Sessions filter"]').click();

    await expect(
      dialog.locator('[data-command-item="new-session"]')
    ).toBeVisible();
  });

  test("Backspace on empty input removes active filter", async ({ page }) => {
    const dialog = await openCommandMenu(page);
    await dialog.locator('[data-command-item="recent-sessions"]').click();
    await expect(dialog.getByText("Sessions")).toBeVisible();

    const input = dialog.getByPlaceholder("Search chat sessions, projects...");
    await input.focus();
    await page.keyboard.press("Backspace");

    await expect(
      dialog.locator('[data-command-item="new-session"]')
    ).toBeVisible();
  });

  test("Backspace on empty input with no filter closes menu", async ({
    page,
  }) => {
    await openCommandMenu(page);
    await page.keyboard.press("Backspace");
    await expect(getCommandMenuContent(page)).not.toBeVisible();
  });

  // -- Search --

  test("Search finds matching chat session", async ({ page }) => {
    const dialog = await openCommandMenu(page);

    const input = dialog.getByPlaceholder("Search chat sessions, projects...");
    await input.fill(`${TEST_PREFIX} Chat 3`);
    await page.waitForTimeout(500);

    await expect(
      dialog.locator(`[data-command-item="chat-${chatSessionIds[2]}"]`)
    ).toBeVisible();

    await expectScreenshot(page, { name: "command-menu-search-results" });
  });

  test("Search finds matching project", async ({ page }) => {
    const dialog = await openCommandMenu(page);

    const input = dialog.getByPlaceholder("Search chat sessions, projects...");
    await input.fill(`${TEST_PREFIX} Project 2`);
    await page.waitForTimeout(500);

    await expect(
      dialog.locator(`[data-command-item="project-${projectIds[1]}"]`)
    ).toBeVisible();
  });

  test('Search shows "Create New Project" action with typed name', async ({
    page,
  }) => {
    const dialog = await openCommandMenu(page);

    const input = dialog.getByPlaceholder("Search chat sessions, projects...");
    await input.fill("my custom project name");

    await expect(
      dialog.locator('[data-command-item="create-project-with-name"]')
    ).toBeVisible();
  });

  test("Search with no results shows empty state", async ({ page }) => {
    const dialog = await openCommandMenu(page);

    const input = dialog.getByPlaceholder("Search chat sessions, projects...");
    await input.fill("xyz123nonexistent9999");
    await page.waitForTimeout(500);

    const noResults = dialog.getByText("No results found");
    const noMore = dialog.getByText("No more results");
    await expect(noResults.or(noMore)).toBeVisible();

    await expectScreenshot(page, { name: "command-menu-no-results" });
  });

  // -- Navigation --

  test('"New Session" navigates to /app', async ({ page }) => {
    // Start from /chat so navigation is observable
    await page.goto("/chat");
    await page.waitForLoadState("networkidle");

    const dialog = await openCommandMenu(page);
    await dialog.locator('[data-command-item="new-session"]').click();

    await page.waitForURL(/\/app/);
    expect(page.url()).toContain("/app");
  });

  test("Clicking a chat session navigates to its URL", async ({ page }) => {
    const dialog = await openCommandMenu(page);

    const input = dialog.getByPlaceholder("Search chat sessions, projects...");
    await input.fill(`${TEST_PREFIX} Chat 1`);
    await page.waitForTimeout(500);

    await dialog
      .locator(`[data-command-item="chat-${chatSessionIds[0]}"]`)
      .click();

    await page.waitForURL(/chatId=/);
    expect(page.url()).toContain(`chatId=${chatSessionIds[0]}`);
  });

  test("Clicking a project navigates to its URL", async ({ page }) => {
    const dialog = await openCommandMenu(page);

    const input = dialog.getByPlaceholder("Search chat sessions, projects...");
    await input.fill(`${TEST_PREFIX} Project 1`);
    await page.waitForTimeout(500);

    await dialog
      .locator(`[data-command-item="project-${projectIds[0]}"]`)
      .click();

    await page.waitForURL(/projectId=/);
    expect(page.url()).toContain(`projectId=${projectIds[0]}`);
  });

  test('"New Project" opens create project modal', async ({ page }) => {
    const dialog = await openCommandMenu(page);
    await dialog.locator('[data-command-item="new-project"]').click();
    await expect(page.getByText("Create New Project")).toBeVisible();
  });

  // -- Menu state --

  test("Menu closes after selecting an item", async ({ page }) => {
    const dialog = await openCommandMenu(page);
    await dialog.locator('[data-command-item="new-session"]').click();
    await expect(getCommandMenuContent(page)).not.toBeVisible();
  });

  test("Escape closes menu", async ({ page }) => {
    await openCommandMenu(page);
    await page.keyboard.press("Escape");
    await expect(getCommandMenuContent(page)).not.toBeVisible();
  });

  test("Menu state resets when reopened", async ({ page }) => {
    let dialog = await openCommandMenu(page);
    await dialog.locator('[data-command-item="recent-sessions"]').click();
    await expect(dialog.getByText("Sessions")).toBeVisible();

    const input = dialog.getByPlaceholder("Search chat sessions, projects...");
    await input.fill("test query");

    await page.keyboard.press("Escape");
    await expect(getCommandMenuContent(page)).not.toBeVisible();

    dialog = await openCommandMenu(page);

    await expect(
      dialog.getByPlaceholder("Search chat sessions, projects...")
    ).toHaveValue("");
    await expect(
      dialog.locator('[data-command-item="new-session"]')
    ).toBeVisible();
  });
});
