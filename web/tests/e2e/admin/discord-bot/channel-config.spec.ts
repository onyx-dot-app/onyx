/**
 * E2E tests for Discord channel configuration.
 *
 * Tests the channel configuration table which shows:
 * - List of channels with icons (text/forum)
 * - Enabled toggle per channel
 * - Require @mention toggle
 * - Thread Only Mode toggle
 * - Agent Override dropdown
 */

import { test, expect, gotoGuildDetailPage } from "./fixtures";

test.describe("Channel Configuration", () => {
  test("channels list displays", async ({ adminPage, mockRegisteredGuild }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Channel list table should be visible
    const channelTable = adminPage.locator("table");
    await expect(channelTable).toBeVisible({ timeout: 10000 });

    // Should show our mock channels
    await expect(adminPage.locator("text=general")).toBeVisible();
    await expect(adminPage.locator("text=help-forum")).toBeVisible();
    await expect(adminPage.locator("text=private-support")).toBeVisible();
  });

  test("channels table has correct columns", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Table headers should be visible
    await expect(adminPage.locator("th:has-text('Channel')")).toBeVisible();
    await expect(adminPage.locator("th:has-text('Enabled')")).toBeVisible();
    await expect(
      adminPage.locator("th:has-text('Require @mention')")
    ).toBeVisible();
    await expect(
      adminPage.locator("th:has-text('Thread Only Mode')")
    ).toBeVisible();
    await expect(
      adminPage.locator("th:has-text('Agent Override')")
    ).toBeVisible();
  });

  test("channel enabled toggle updates state", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Find the row for "general" channel
    const generalRow = adminPage.locator("tr").filter({
      hasText: "general",
    });

    // Find the first switch in that row (Enabled toggle)
    const enabledToggle = generalRow.locator('[role="switch"]').first();
    await expect(enabledToggle).toBeVisible({ timeout: 10000 });

    // Get initial state
    const initialState = await enabledToggle.getAttribute("aria-checked");

    // Click to toggle
    await enabledToggle.click();

    // State should change (local state update)
    await expect(enabledToggle).toHaveAttribute(
      "aria-checked",
      initialState === "true" ? "false" : "true"
    );
  });

  test("channel require mention toggle works", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Find the row for "general" channel
    const generalRow = adminPage.locator("tr").filter({
      hasText: "general",
    });

    // Find switches - second one should be "require @mention"
    const switches = generalRow.locator('[role="switch"]');
    const requireMentionToggle = switches.nth(1);

    await expect(requireMentionToggle).toBeVisible({ timeout: 10000 });

    // Get initial state
    const initialState =
      await requireMentionToggle.getAttribute("aria-checked");

    // Click to toggle
    await requireMentionToggle.click();

    // State should change
    await expect(requireMentionToggle).toHaveAttribute(
      "aria-checked",
      initialState === "true" ? "false" : "true"
    );
  });

  test("channel thread only mode toggle works for text channels", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Find the row for "general" channel (text type)
    const generalRow = adminPage.locator("tr").filter({
      hasText: "general",
    });

    // Find switches - third one should be "thread only mode"
    const switches = generalRow.locator('[role="switch"]');
    const threadOnlyToggle = switches.nth(2);

    await expect(threadOnlyToggle).toBeVisible({ timeout: 10000 });

    // Toggle should be clickable for text channels
    await threadOnlyToggle.click();

    // Verify it changed
    const newState = await threadOnlyToggle.getAttribute("aria-checked");
    expect(newState).toBe("true");
  });

  test("forum channels do not show thread only toggle", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Find the row for "help-forum" channel (forum type)
    const forumRow = adminPage.locator("tr").filter({
      hasText: "help-forum",
    });

    // Forum channels should only have 2 switches (Enabled, Require @mention)
    // Thread Only Mode is not applicable to forums
    const switches = forumRow.locator('[role="switch"]');
    const count = await switches.count();

    // Should have fewer switches than text channels (2 vs 3)
    expect(count).toBe(2);
  });

  test("enable all button works", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Click "Enable All" button
    const enableAllButton = adminPage.locator('button:has-text("Enable All")');
    await expect(enableAllButton).toBeVisible({ timeout: 10000 });
    await enableAllButton.click();

    // Wait for UI to update
    await adminPage.waitForTimeout(300);

    // First toggle in each row should be enabled
    const rows = adminPage.locator("tbody tr");
    const rowCount = await rows.count();

    for (let i = 0; i < rowCount; i++) {
      const toggle = rows.nth(i).locator('[role="switch"]').first();
      if (await toggle.isVisible()) {
        await expect(toggle).toHaveAttribute("aria-checked", "true");
      }
    }
  });

  test("disable all button works", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Click "Disable All" button
    const disableAllButton = adminPage.locator(
      'button:has-text("Disable All")'
    );
    await expect(disableAllButton).toBeVisible({ timeout: 10000 });
    await disableAllButton.click();

    // Wait for UI to update
    await adminPage.waitForTimeout(300);

    // First toggle in each row should be disabled
    const rows = adminPage.locator("tbody tr");
    const rowCount = await rows.count();

    for (let i = 0; i < rowCount; i++) {
      const toggle = rows.nth(i).locator('[role="switch"]').first();
      if (await toggle.isVisible()) {
        await expect(toggle).toHaveAttribute("aria-checked", "false");
      }
    }
  });

  test("unsaved changes indicator appears", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Initially no unsaved changes indicator
    const unsavedMessage = adminPage.locator("text=You have unsaved changes");
    await expect(unsavedMessage).not.toBeVisible();

    // Make a change
    const generalRow = adminPage.locator("tr").filter({
      hasText: "general",
    });
    const enabledToggle = generalRow.locator('[role="switch"]').first();
    await enabledToggle.click();

    // Unsaved changes indicator should appear
    await expect(unsavedMessage).toBeVisible({ timeout: 5000 });
  });
});
