/**
 * E2E tests for Discord guild detail page and channel configuration.
 *
 * Tests the guild detail page which includes:
 * - Guild enabled/disabled toggle
 * - Default Agent (persona) selector
 * - Channel Configuration section with:
 *   - List of channels with icons (text/forum)
 *   - Enabled toggle per channel
 *   - Require @mention toggle
 *   - Thread Only Mode toggle
 *   - Agent Override dropdown
 */

import {
  test,
  expect,
  gotoGuildDetailPage,
} from "@tests/e2e/admin/discord-bot/fixtures";

// Disable retries for Discord bot tests - attempt once at most
test.describe.configure({ retries: 0 });

test.describe("Guild Detail Page & Channel Configuration", () => {
  test("guild detail page loads", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Page should load with guild info
    await expect(adminPage).toHaveURL(
      new RegExp(`/admin/discord-bot/${mockRegisteredGuild.id}`)
    );

    // Should show the guild name in the header
    await expect(
      adminPage.locator(`text=${mockRegisteredGuild.name}`)
    ).toBeVisible();
  });

  test("guild default agent dropdown shows options", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Should show "Default Agent" section
    await expect(adminPage.locator("text=Default Agent").first()).toBeVisible({
      timeout: 10000,
    });

    // Find the persona/agent dropdown (InputSelect)
    const agentDropdown = adminPage.locator(
      'button:has-text("Default Assistant")'
    );

    if (await agentDropdown.isVisible({ timeout: 5000 }).catch(() => false)) {
      await agentDropdown.click();

      // Dropdown should show available options
      const options = adminPage.locator('[role="option"]');
      await expect(options.first()).toBeVisible({ timeout: 5000 });
    }
  });
});

test.describe("Channel Configuration", () => {
  test("channels table displays with action buttons", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Channel list table should be visible
    const channelTable = adminPage.locator("table");
    await expect(channelTable).toBeVisible({ timeout: 10000 });

    // Should show our mock channels
    await expect(adminPage.locator("text=general")).toBeVisible();
    await expect(adminPage.locator("text=help-forum")).toBeVisible();
    await expect(adminPage.locator("text=private-support")).toBeVisible();

    // Should show action buttons
    await expect(
      adminPage.locator('button:has-text("Enable All")')
    ).toBeVisible();
    await expect(
      adminPage.locator('button:has-text("Disable All")')
    ).toBeVisible();
    // Update button is now in the header, not in the channel config section
    await expect(
      adminPage.locator('button:has-text("Update Configuration")')
    ).toBeVisible();
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

    const enableAllButton = adminPage.locator('button:has-text("Enable All")');
    await expect(enableAllButton).toBeVisible({ timeout: 10000 });
    await enableAllButton.click();

    // Wait for UI to update - all enabled toggles should be checked
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

    const disableAllButton = adminPage.locator(
      'button:has-text("Disable All")'
    );
    await expect(disableAllButton).toBeVisible({ timeout: 10000 });
    await disableAllButton.click();

    // Wait for UI to update - all enabled toggles should be unchecked
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

    // Find the unsaved changes message container (always in DOM, hidden with opacity-0)
    const unsavedMessage = adminPage.locator("text=You have unsaved changes");
    // The container div has class "sticky" and controls visibility via opacity
    const messageContainer = adminPage
      .locator("div.sticky")
      .filter({ has: unsavedMessage })
      .first();

    // Initially hidden (opacity-0)
    await expect(messageContainer).toHaveCSS("opacity", "0");

    // Make a change
    const generalRow = adminPage.locator("tr").filter({
      hasText: "general",
    });
    const enabledToggle = generalRow.locator('[role="switch"]').first();
    await enabledToggle.click();

    // Unsaved changes indicator should appear (opacity-100)
    await expect(messageContainer).toHaveCSS("opacity", "1", { timeout: 5000 });
    await expect(unsavedMessage).toBeVisible({ timeout: 5000 });
  });
});
