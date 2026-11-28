import { test, expect, Page, Locator } from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { ChatSearchCommandMenu } from "@tests/e2e/pages/ChatSearchCommandMenu";
import { expectScreenshot } from "@tests/e2e/utils/visualRegression";

// Test data storage
const TEST_PREFIX = "E2E-CMD";
let chatSessionIds: string[] = [];

// Chat/project rows render a relative timestamp (e.g. "3 seconds ago") whose
// value depends on the wall clock, making screenshots non-deterministic. Mask
// it so visual-regression diffs ignore the timestamp cells.
const TIMESTAMP_MASK = '[data-testid="command-menu-timestamp"]';

/**
 * Helper to get the command menu dialog locator (using the content wrapper)
 */
function getCommandMenuContent(page: Page): Locator {
  return new ChatSearchCommandMenu(page).dialog;
}

/**
 * Helper to open the command menu and return a scoped locator
 */
async function openCommandMenu(page: Page): Promise<Locator> {
  const menu = new ChatSearchCommandMenu(page);
  await menu.open();
  return menu.dialog;
}

test.describe("Chat Search Command Menu", () => {
  test.beforeAll(async ({ browser }, workerInfo) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await loginAsWorkerUser(page, workerInfo.workerIndex);
    const client = new OnyxApiClient(page.request);

    await page.goto("/app");
    await page.waitForLoadState("networkidle");

    for (let i = 1; i <= 5; i++) {
      const id = await client.createChatSession(`${TEST_PREFIX} Chat ${i}`);
      chatSessionIds.push(id);
    }

    await context.close();
  });

  test.afterAll(async ({ browser }, workerInfo) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await loginAsWorkerUser(page, workerInfo.workerIndex);
    const client = new OnyxApiClient(page.request);

    await page.goto("/app");
    await page.waitForLoadState("networkidle");

    for (const id of chatSessionIds) {
      await client.deleteChatSession(id);
    }

    await context.close();
  });

  test.beforeEach(async ({ page }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
  });

  // -- Opening --

  test("Opens with search input, New Session action, and correct positioning", async ({
    page,
  }) => {
    const dialog = await openCommandMenu(page);

    await expect(new ChatSearchCommandMenu(page).input).toBeFocused();
    await expect(
      dialog.locator('[data-command-item="new-session"]')
    ).toBeVisible();

    await expectScreenshot(page, {
      name: "command-menu-default-open",
      mask: [TIMESTAMP_MASK],
    });
  });

  // -- Preview limits --

  // -- Filter expansion --

  test('"Recent Sessions" filter expands to show all 5 chats', async ({
    page,
  }) => {
    const dialog = await openCommandMenu(page);
    await dialog.locator('[data-command-item="recent-sessions"]').click();

    for (let i = 1; i <= 5; i++) {
      await expect(
        dialog.locator(`[data-command-item="chat-${chatSessionIds[i - 1]}"]`)
      ).toBeVisible();
    }

    await expect(dialog.getByText("Sessions")).toBeVisible();
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

    const input = new ChatSearchCommandMenu(page).input;
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
    const menu = new ChatSearchCommandMenu(page);
    await menu.open();
    await menu.searchChats(`${TEST_PREFIX} Chat 3`);
    const { dialog } = menu;
    await expect(
      dialog.locator(`[data-command-item="chat-${chatSessionIds[2]}"]`)
    ).toBeVisible();

    await expectScreenshot(page, {
      name: "command-menu-search-results",
      mask: [TIMESTAMP_MASK],
    });
  });

  test("Search with no results shows empty state", async ({ page }) => {
    const menu = new ChatSearchCommandMenu(page);
    await menu.open();
    await menu.searchChats("xyz123nonexistent9999");
    const { dialog } = menu;
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
    const menu = new ChatSearchCommandMenu(page);
    await menu.open();
    await menu.searchChats(`${TEST_PREFIX} Chat 1`);
    const { dialog } = menu;
    await dialog
      .locator(`[data-command-item="chat-${chatSessionIds[0]}"]`)
      .click();

    await page.waitForURL(/chatId=/);
    expect(page.url()).toContain(`chatId=${chatSessionIds[0]}`);
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

    const input = new ChatSearchCommandMenu(page).input;
    await input.fill("test query");

    await page.keyboard.press("Escape");
    await expect(getCommandMenuContent(page)).not.toBeVisible();

    dialog = await openCommandMenu(page);

    await expect(new ChatSearchCommandMenu(page).input).toHaveValue("");
    await expect(
      dialog.locator('[data-command-item="new-session"]')
    ).toBeVisible();
  });
});
