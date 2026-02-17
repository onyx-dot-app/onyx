import { test, expect, Page, Locator } from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

test.use({ storageState: "admin_auth.json" });

// Test data storage
const TEST_PREFIX = `E2E-CMD-${Date.now()}`;
let chatSessionIds: string[] = [];
let projectIds: number[] = [];

/**
 * Helper to get the command menu dialog locator (using the content wrapper)
 */
function getCommandMenuContent(page: Page): Locator {
  // Use DialogPrimitive.Content which has role="dialog" and contains the visually-hidden title
  return page.locator('[role="dialog"]:has([data-command-menu-list])');
}

/**
 * Helper to get the command menu list locator
 */
function getCommandMenuList(page: Page): Locator {
  return page.locator("[data-command-menu-list]");
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
  // Create all test data ONCE before all tests
  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const page = await context.newPage();
    const client = new OnyxApiClient(page.request);

    // Navigate to app to establish session
    await page.goto("/app");
    await page.waitForLoadState("networkidle");

    // Create 5 chat sessions
    for (let i = 1; i <= 5; i++) {
      const id = await client.createChatSession(`${TEST_PREFIX} Chat ${i}`);
      chatSessionIds.push(id);
    }

    // Create 4 projects
    for (let i = 1; i <= 4; i++) {
      const id = await client.createProject(`${TEST_PREFIX} Project ${i}`);
      projectIds.push(id);
    }

    await context.close();
  });

  // Cleanup all test data ONCE after all tests
  test.afterAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const page = await context.newPage();
    const client = new OnyxApiClient(page.request);

    // Navigate to app to establish session
    await page.goto("/app");
    await page.waitForLoadState("networkidle");

    // Delete chat sessions
    for (const id of chatSessionIds) {
      await client.deleteChatSession(id);
    }

    // Delete projects
    for (const id of projectIds) {
      await client.deleteProject(id);
    }

    await context.close();
  });

  test.describe("Menu Opening", () => {
    test("Opens when clicking sidebar search trigger", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      await expect(
        dialog.getByPlaceholder("Search chat sessions, projects...")
      ).toBeVisible();
      // "New Session" action should be visible within the command menu
      await expect(
        dialog.locator('[data-command-item="new-session"]')
      ).toBeVisible();
    });

    test("Shows search input with placeholder and focus", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      const input = dialog.getByPlaceholder(
        "Search chat sessions, projects..."
      );
      await expect(input).toBeVisible();
      await expect(input).toBeFocused();
    });

    test('Shows "New Session" action when no search term', async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // Use data-command-item attribute to target the action
      await expect(
        dialog.locator('[data-command-item="new-session"]')
      ).toBeVisible();
    });
  });

  test.describe("Preview Display", () => {
    test("Shows at most 4 chat sessions (PREVIEW_CHATS_LIMIT)", async ({
      page,
    }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // Should show at most 4 chat sessions in preview mode
      const chatItems = dialog.locator('[data-command-item^="chat-"]');
      const chatCount = await chatItems.count();
      // In "all" filter with no search, should show max 4 chats
      expect(chatCount).toBeLessThanOrEqual(4);
    });

    test("Shows at most 3 projects (PREVIEW_PROJECTS_LIMIT)", async ({
      page,
    }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // Should show at most 3 projects in preview mode
      const projectItems = dialog.locator('[data-command-item^="project-"]');
      const projectCount = await projectItems.count();
      // In "all" filter with no search, should show max 3 projects
      expect(projectCount).toBeLessThanOrEqual(3);
    });

    test('Shows "Recent Sessions" filter', async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // The "Recent Sessions" filter should be visible
      await expect(
        dialog.locator('[data-command-item="recent-sessions"]')
      ).toBeVisible();
    });

    test('Shows "Projects" filter', async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // The "Projects" filter should be visible
      await expect(
        dialog.locator('[data-command-item="projects"]')
      ).toBeVisible();
    });

    test('Shows "New Project" action', async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      await expect(
        dialog.locator('[data-command-item="new-project"]')
      ).toBeVisible();
    });
  });

  test.describe("Filter Expansion", () => {
    test('Click "Recent Sessions" filter shows all 5 chats', async ({
      page,
    }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // Click on Recent Sessions filter to expand
      await dialog.locator('[data-command-item="recent-sessions"]').click();

      // Wait for the filter to be applied and all chats to load
      await page.waitForTimeout(500);

      // Should now show all 5 test chats - use data-command-item to find them
      for (let i = 1; i <= 5; i++) {
        await expect(
          dialog.locator(`[data-command-item="chat-${chatSessionIds[i - 1]}"]`)
        ).toBeVisible();
      }
    });

    test('Filter chip "Sessions" appears in header when chats filter is active', async ({
      page,
    }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // Click on Recent Sessions filter
      await dialog.locator('[data-command-item="recent-sessions"]').click();

      // The filter chip should appear (look for the editable tag with "Sessions")
      await expect(dialog.getByText("Sessions")).toBeVisible();
    });

    test('Click "Projects" filter shows all 4 projects', async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // Click on Projects filter to expand
      await dialog.locator('[data-command-item="projects"]').click();

      // Wait for the filter to be applied
      await page.waitForTimeout(500);

      // Should now show all 4 test projects - use data-command-item to find them
      for (let i = 1; i <= 4; i++) {
        await expect(
          dialog.locator(`[data-command-item="project-${projectIds[i - 1]}"]`)
        ).toBeVisible();
      }
    });

    test("Clicking filter chip X removes filter and returns to 'all'", async ({
      page,
    }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // Click on Recent Sessions filter
      await dialog.locator('[data-command-item="recent-sessions"]').click();

      // Wait for the filter to be applied
      await expect(dialog.getByText("Sessions")).toBeVisible();

      // Click the X on the filter tag to remove it (aria-label is "Remove Sessions filter")
      await dialog
        .locator('button[aria-label="Remove Sessions filter"]')
        .click();

      // Should be back to "all" view - "New Session" action should be visible again
      await expect(
        dialog.locator('[data-command-item="new-session"]')
      ).toBeVisible();
    });

    test("Backspace on empty input removes active filter", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // Click on Recent Sessions filter
      await dialog.locator('[data-command-item="recent-sessions"]').click();

      // Wait for the filter to be applied
      await expect(dialog.getByText("Sessions")).toBeVisible();

      // Ensure focus is on the input field
      const input = dialog.getByPlaceholder(
        "Search chat sessions, projects..."
      );
      await input.focus();

      // Press backspace on empty input to remove filter
      await page.keyboard.press("Backspace");

      // Should be back to "all" view
      await expect(
        dialog.locator('[data-command-item="new-session"]')
      ).toBeVisible();
    });

    test("Backspace on empty input with no filter closes menu", async ({
      page,
    }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      await openCommandMenu(page);

      // Press backspace on empty input (no filter active)
      await page.keyboard.press("Backspace");

      // Menu should close
      await expect(getCommandMenuContent(page)).not.toBeVisible();
    });
  });

  test.describe("Search Filtering", () => {
    test("Search finds matching chat session", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      const input = dialog.getByPlaceholder(
        "Search chat sessions, projects..."
      );
      await input.fill(`${TEST_PREFIX} Chat 3`);

      // Wait for search results
      await page.waitForTimeout(500);

      // Should show the matching chat - use specific data-command-item
      await expect(
        dialog.locator(`[data-command-item="chat-${chatSessionIds[2]}"]`)
      ).toBeVisible();
    });

    test("Search finds matching project", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      const input = dialog.getByPlaceholder(
        "Search chat sessions, projects..."
      );
      await input.fill(`${TEST_PREFIX} Project 2`);

      // Wait for search results
      await page.waitForTimeout(500);

      // Should show the matching project - use specific data-command-item
      await expect(
        dialog.locator(`[data-command-item="project-${projectIds[1]}"]`)
      ).toBeVisible();
    });

    test('Search shows "Create New Project" action with typed name', async ({
      page,
    }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      const input = dialog.getByPlaceholder(
        "Search chat sessions, projects..."
      );
      await input.fill("my custom project name");

      // Should show create project action with the search term
      await expect(
        dialog.locator('[data-command-item="create-project-with-name"]')
      ).toBeVisible();
    });

    test('Search with no results shows "No results found"', async ({
      page,
    }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      const input = dialog.getByPlaceholder(
        "Search chat sessions, projects..."
      );
      await input.fill("xyz123nonexistent9999");

      // Wait for search to complete
      await page.waitForTimeout(500);

      // Should show no results message or the "No more results" separator
      // The component shows "No results found" when there are no matches
      const noResults = dialog.getByText("No results found");
      const noMore = dialog.getByText("No more results");
      await expect(noResults.or(noMore)).toBeVisible();
    });
  });

  test.describe("Navigation Actions", () => {
    test('"New Session" click navigates to /app', async ({ page }) => {
      await page.goto("/chat");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // Click New Session action
      await dialog.locator('[data-command-item="new-session"]').click();

      // Should navigate to /app
      await page.waitForURL(/\/app/);
      expect(page.url()).toContain("/app");
    });

    test("Click chat session navigates to /chat?chatId={id}", async ({
      page,
    }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // Search for a specific chat
      const input = dialog.getByPlaceholder(
        "Search chat sessions, projects..."
      );
      await input.fill(`${TEST_PREFIX} Chat 1`);

      // Wait for search results
      await page.waitForTimeout(500);

      // Click on the chat using data-command-item
      await dialog
        .locator(`[data-command-item="chat-${chatSessionIds[0]}"]`)
        .click();

      // Should navigate to the chat URL
      await page.waitForURL(/chatId=/);
      expect(page.url()).toContain(`chatId=${chatSessionIds[0]}`);
    });

    test("Click project navigates to /chat?projectId={id}", async ({
      page,
    }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // Search for a specific project
      const input = dialog.getByPlaceholder(
        "Search chat sessions, projects..."
      );
      await input.fill(`${TEST_PREFIX} Project 1`);

      // Wait for search results
      await page.waitForTimeout(500);

      // Click on the project using data-command-item
      await dialog
        .locator(`[data-command-item="project-${projectIds[0]}"]`)
        .click();

      // Should navigate to the project URL
      await page.waitForURL(/projectId=/);
      expect(page.url()).toContain(`projectId=${projectIds[0]}`);
    });

    test('"New Project" click opens create project modal', async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // Click New Project action
      await dialog.locator('[data-command-item="new-project"]').click();

      // Should open the create project modal
      await expect(page.getByText("Create New Project")).toBeVisible();
    });
  });

  test.describe("Menu State", () => {
    test("Menu closes after selecting an action/item", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const dialog = await openCommandMenu(page);

      // Select New Session
      await dialog.locator('[data-command-item="new-session"]').click();

      // Menu should close
      await expect(getCommandMenuContent(page)).not.toBeVisible();
    });

    test("Menu state resets when reopened (search cleared, filter reset)", async ({
      page,
    }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // Open menu and apply a filter first (filter is only visible when search is empty)
      let dialog = await openCommandMenu(page);
      await dialog.locator('[data-command-item="recent-sessions"]').click();

      // Wait for the filter to be applied
      await expect(dialog.getByText("Sessions")).toBeVisible();

      // Now type something in the search
      const input = dialog.getByPlaceholder(
        "Search chat sessions, projects..."
      );
      await input.fill("test query");

      // Close with Escape
      await page.keyboard.press("Escape");

      // Wait for menu to close
      await expect(getCommandMenuContent(page)).not.toBeVisible();

      // Reopen
      dialog = await openCommandMenu(page);

      // Search input should be empty
      await expect(
        dialog.getByPlaceholder("Search chat sessions, projects...")
      ).toHaveValue("");

      // Should be back to "all" view with "New Session" action visible
      await expect(
        dialog.locator('[data-command-item="new-session"]')
      ).toBeVisible();
    });

    test("Escape closes menu", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      await openCommandMenu(page);

      // Press Escape
      await page.keyboard.press("Escape");

      // Menu should close
      await expect(getCommandMenuContent(page)).not.toBeVisible();
    });
  });
});
