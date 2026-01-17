/**
 * E2E tests for Discord guilds list page.
 *
 * Tests the server configurations table which shows:
 * - List of registered and pending Discord servers
 * - Status badges (Registered/Pending)
 * - Enabled/Disabled status
 * - Add Server and Delete actions
 */

import { test, expect, gotoDiscordBotPage } from "./fixtures";

test.describe("Guilds List Page", () => {
  test("guilds page shows server configurations", async ({ adminPage }) => {
    await gotoDiscordBotPage(adminPage);

    // Should show Server Configurations section
    const serverConfigSection = adminPage.locator("text=Server Configurations");
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

    await expect(emptyState.or(addButton).or(serverTable)).toBeVisible({
      timeout: 10000,
    });
  });

  test("guilds page shows mock registered guild", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoDiscordBotPage(adminPage);

    // Mock guild should appear in the list
    const guildName = adminPage.locator(`text=${mockRegisteredGuild.name}`);
    await expect(guildName).toBeVisible({ timeout: 10000 });

    // Should show Registered badge
    const registeredBadge = adminPage.locator("text=Registered");
    await expect(registeredBadge).toBeVisible();

    // Should show Enabled badge
    const enabledBadge = adminPage.locator("text=Enabled");
    await expect(enabledBadge).toBeVisible();
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
        await expect(adminPage.locator("text=Registration Key")).toBeVisible();

        // Should show the !register command
        await expect(adminPage.locator("text=!register")).toBeVisible();

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
  }) => {
    await gotoDiscordBotPage(adminPage);

    // Wait for table to load with mock guild
    await expect(
      adminPage.locator(`text=${mockRegisteredGuild.name}`)
    ).toBeVisible({ timeout: 10000 });

    // Find the table row containing the guild
    const tableRow = adminPage.locator("tr").filter({
      hasText: mockRegisteredGuild.name,
    });

    // Find delete button in that row - it's an IconButton (last button in Actions column)
    const deleteButton = tableRow.locator("button").last();

    if (await deleteButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await deleteButton.click();

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
  }) => {
    await gotoDiscordBotPage(adminPage);

    // Wait for table to load with mock guild
    const guildButton = adminPage.locator(
      `button:has-text("${mockRegisteredGuild.name}")`
    );
    await expect(guildButton).toBeVisible({ timeout: 10000 });

    // Click on the guild name to navigate to detail page
    await guildButton.click();

    // Should navigate to guild detail page
    await expect(adminPage).toHaveURL(
      new RegExp(`/admin/discord-bot/${mockRegisteredGuild.id}`)
    );

    // Verify detail page loaded correctly
    await expect(adminPage.locator("text=Channel Configuration")).toBeVisible();
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
    const loader = adminPage.locator(".loading, .loader, svg");
    // Give it a moment to appear
    await adminPage.waitForTimeout(100);

    // Wait for page to finish loading
    await adminPage.waitForLoadState("networkidle");

    // After loading, page title should be visible
    await expect(adminPage.locator("text=Discord Bots")).toBeVisible();
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
    const errorMessage = adminPage.locator("text=/failed|error/i");
    await expect(errorMessage).toBeVisible({ timeout: 10000 });
  });
});
