/**
 * E2E tests for Discord guilds list page.
 *
 * Tests the server configurations table which shows:
 * - List of registered and pending Discord servers
 * - Status badges (Registered/Pending)
 * - Enabled/Disabled status
 * - Add Server and Delete actions
 */

import {
  test,
  expect,
  gotoDiscordBotPage,
} from "@tests/e2e/admin/discord-bot/fixtures";

// Disable retries for Discord bot tests - attempt once at most
test.describe.configure({ retries: 0 });

test.describe("Guilds List Page", () => {
  test("guilds page shows server configurations", async ({ adminPage }) => {
    await gotoDiscordBotPage(adminPage);

    // Should show Server Configurations section
    // Use .first() to avoid strict mode violation if it appears in multiple places
    const serverConfigSection = adminPage
      .locator("text=Server Configurations")
      .first();
    await expect(serverConfigSection).toBeVisible({ timeout: 10000 });
  });

  test("guilds page empty state", async ({ adminPage }) => {
    await gotoDiscordBotPage(adminPage);

    // Should show either:
    // - "No Discord servers configured yet" empty message
    // - OR a table with servers
    // - OR Add Server button
    const emptyState = adminPage.locator(
      "text=No Discord servers configured yet"
    );
    const addButton = adminPage.locator('button:has-text("Add Server")');
    const serverTable = adminPage.locator("table");

    // Check each state separately to avoid strict mode violation
    // (empty state and add button can both be visible when bot not configured)
    const hasEmptyState = await emptyState
      .isVisible({ timeout: 5000 })
      .catch(() => false);
    const hasAddButton = await addButton
      .isVisible({ timeout: 5000 })
      .catch(() => false);
    const hasTable = await serverTable
      .isVisible({ timeout: 5000 })
      .catch(() => false);

    expect(hasEmptyState || hasAddButton || hasTable).toBe(true);
  });

  test("guilds page shows mock registered guild", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoDiscordBotPage(adminPage);

    // Mock guild should appear in the list
    const guildName = adminPage.locator(`text=${mockRegisteredGuild.name}`);
    await expect(guildName).toBeVisible({ timeout: 10000 });

    // Find the table row containing the guild to scope badges
    const tableRow = adminPage.locator("tr").filter({
      hasText: mockRegisteredGuild.name,
    });

    // Should show Registered badge in the guild's row
    const registeredBadge = tableRow.locator("text=Registered");
    await expect(registeredBadge).toBeVisible();

    // Should show enabled toggle switch in the guild's row (in Enabled column)
    const enabledSwitch = tableRow.locator('[role="switch"]').first();
    await expect(enabledSwitch).toBeVisible();
    await expect(enabledSwitch).toHaveAttribute("aria-checked", "true");
  });

  test("guild enabled toggle works in table", async ({
    adminPage,
    mockRegisteredGuild,
    mockBotConfigured: _mockBotConfigured,
  }) => {
    await gotoDiscordBotPage(adminPage);

    // Find the table row containing the guild
    const tableRow = adminPage.locator("tr").filter({
      hasText: mockRegisteredGuild.name,
    });
    await expect(tableRow).toBeVisible({ timeout: 10000 });

    // Find the enabled toggle switch in that row
    const enabledSwitch = tableRow.locator('[role="switch"]').first();
    await expect(enabledSwitch).toBeVisible({ timeout: 10000 });
    await expect(enabledSwitch).toHaveAttribute("aria-checked", "true");
    await expect(enabledSwitch).toBeEnabled();

    const initialState = await enabledSwitch.getAttribute("aria-checked");
    const expectedState = initialState === "true" ? "false" : "true";
    const guildUrl = `/api/manage/admin/discord-bot/guilds/${mockRegisteredGuild.id}`;
    const guildsListUrl = `/api/manage/admin/discord-bot/guilds`;

    // Set up response waiters before clicking
    const patchPromise = adminPage.waitForResponse(
      (response) =>
        response.url().includes(guildUrl) &&
        response.request().method() === "PATCH"
    );

    // refreshGuilds() calls the list endpoint, not the individual guild endpoint
    const getPromise = adminPage.waitForResponse(
      (response) =>
        response.url().includes(guildsListUrl) &&
        response.request().method() === "GET"
    );

    await enabledSwitch.click();

    // Wait for PATCH then GET (refreshGuilds) to complete
    await patchPromise;
    await getPromise;

    // Verify the toggle state changed
    await expect(enabledSwitch).toHaveAttribute("aria-checked", expectedState);
  });

  test("guilds page add server modal and copy key", async ({ adminPage }) => {
    await gotoDiscordBotPage(adminPage);

    const addButton = adminPage.locator('button:has-text("Add Server")');

    if (await addButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      // Button might be disabled if bot not configured
      if (await addButton.isEnabled()) {
        await addButton.click();

        // Should show modal with registration key
        const modal = adminPage.locator('[role="dialog"]');
        await expect(modal).toBeVisible({ timeout: 10000 });

        // Modal should show "Registration Key" title
        await expect(modal.getByText("Registration Key")).toBeVisible();

        // Should show the !register command (scoped to modal)
        await expect(modal.getByText("!register")).toBeVisible();

        // Find and click copy button
        const copyButton = adminPage.locator("button").filter({
          has: adminPage.locator("svg"),
        });

        const copyButtons = await copyButton.all();
        for (const btn of copyButtons) {
          const ariaLabel = await btn.getAttribute("aria-label");
          if (ariaLabel?.toLowerCase().includes("copy")) {
            await btn.click();

            // Toast notification should appear
            const toast = adminPage.locator("text=/copied/i");
            await expect(toast).toBeVisible({ timeout: 5000 });
            break;
          }
        }
      }
    }
  });

  test("guilds page delete shows confirmation", async ({
    adminPage,
    mockRegisteredGuild,
    mockBotConfigured: _mockBotConfigured,
  }) => {
    await gotoDiscordBotPage(adminPage);

    // Wait for table to load with mock guild
    await expect(
      adminPage.locator(`text=${mockRegisteredGuild.name}`)
    ).toBeVisible({ timeout: 10000 });

    // Wait for table to be fully loaded and stable
    await adminPage.waitForLoadState("networkidle");

    // Find the table row containing the guild
    const tableRow = adminPage.locator("tr").filter({
      hasText: mockRegisteredGuild.name,
    });
    await expect(tableRow).toBeVisible({ timeout: 10000 });

    // Find delete button in that row - it's an IconButton (last button in Actions column)
    // The DeleteButton uses IconButton with tooltip="Delete" and SvgTrash icon
    const deleteButton = tableRow.locator("button").last();

    if (await deleteButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      // Ensure the button is visible and scrolled into view
      await deleteButton.scrollIntoViewIfNeeded();
      await deleteButton.waitFor({ state: "visible" });

      // Wait for any animations/transitions to complete
      await adminPage.waitForTimeout(300);

      // Use force click to bypass any overlay/interception issues
      // The SettingsLayouts.Body div may be intercepting pointer events
      await deleteButton.click({ force: true });

      // Confirmation modal should appear
      const modal = adminPage.locator('[role="dialog"]');
      await expect(modal).toBeVisible({ timeout: 10000 });

      // Cancel to avoid actually deleting
      const cancelButton = adminPage.locator('button:has-text("Cancel")');
      if (await cancelButton.isVisible({ timeout: 5000 }).catch(() => false)) {
        await cancelButton.click();
        await expect(modal).not.toBeVisible({ timeout: 5000 });
      }
    }
  });

  test("guilds page navigate to guild detail", async ({
    adminPage,
    mockRegisteredGuild,
    mockBotConfigured: _mockBotConfigured,
  }) => {
    // Wait for bot config API to complete to ensure Card is enabled
    // The Card is disabled when bot is not configured
    // Set up the wait BEFORE navigation so we can catch the response
    const configResponsePromise = adminPage.waitForResponse(
      (response) =>
        response.url().includes("/api/manage/admin/discord-bot/config") &&
        response.request().method() === "GET"
    );

    await gotoDiscordBotPage(adminPage);
    await configResponsePromise;

    // Wait for table to load with mock guild
    const guildButton = adminPage.locator(
      `button:has-text("${mockRegisteredGuild.name}")`
    );
    await expect(guildButton).toBeVisible({ timeout: 10000 });

    // Ensure button is enabled (it's disabled if bot not configured or guild not registered)
    // mockBotConfigured ensures bot is configured, mockRegisteredGuild ensures guild is registered
    await expect(guildButton).toBeEnabled();

    // Click on the guild name to navigate to detail page
    await guildButton.click();

    // Should navigate to guild detail page
    await expect(adminPage).toHaveURL(
      new RegExp(`/admin/discord-bot/${mockRegisteredGuild.id}`)
    );

    // Verify detail page loaded correctly
    // "Channel Configuration" is in a LineItemLayout in the body content, not the page title
    await expect(
      adminPage.locator("text=Channel Configuration").first()
    ).toBeVisible();
  });

  test("loading state shows loader", async ({ adminPage }) => {
    // Intercept API to delay response
    await adminPage.route(
      "**/api/manage/admin/discord-bot/**",
      async (route) => {
        await new Promise((r) => setTimeout(r, 1000));
        await route.continue();
      }
    );

    await adminPage.goto("/admin/discord-bot");

    // Should show loading indicator (ThreeDotsLoader)
    // The loader should appear while data is being fetched
    // ThreeDotsLoader uses react-loader-spinner's ThreeDots with ariaLabel="grid-loading"
    const loader = adminPage.locator('[aria-label="grid-loading"]');
    // Give it a moment to appear
    await expect(loader).toBeVisible({ timeout: 5000 });

    // Wait for page to finish loading
    await adminPage.waitForLoadState("networkidle");

    // After loading, page title should be visible
    await expect(
      adminPage
        .locator('[aria-label="admin-page-title"]')
        .getByText("Discord Bots")
    ).toBeVisible();
  });

  test("error state shows error message", async ({ adminPage }) => {
    // Intercept API to return error
    await adminPage.route("**/api/manage/admin/discord-bot/guilds", (route) => {
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Internal Server Error" }),
      });
    });

    await adminPage.goto("/admin/discord-bot");
    await adminPage.waitForLoadState("networkidle");

    // Should show error message from ErrorCallout
    // ErrorCallout shows both title ("Failed to load Discord servers") and detail ("Internal Server Error")
    // Use .first() to get the first matching element (the title)
    const errorMessage = adminPage.locator("text=/failed|error/i").first();
    await expect(errorMessage).toBeVisible({ timeout: 10000 });
  });
});
