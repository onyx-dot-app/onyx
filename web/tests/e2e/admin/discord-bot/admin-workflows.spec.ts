/**
 * E2E tests for Discord bot admin workflow flows.
 *
 * These tests verify complete user journeys through the Discord bot admin UI.
 */

import {
  test,
  expect,
  gotoDiscordBotPage,
  gotoGuildDetailPage,
} from "./fixtures";

test.describe("Admin Workflow E2E Flows", () => {
  test("full setup flow - view page and add server", async ({ adminPage }) => {
    // Navigate to Discord bot admin page
    await gotoDiscordBotPage(adminPage);

    // Should show page title
    await expect(adminPage.locator("text=Discord Bots")).toBeVisible();

    // Should show Server Configurations section
    await expect(adminPage.locator("text=Server Configurations")).toBeVisible();

    // Should show Add Server button
    const addServerButton = adminPage.locator('button:has-text("Add Server")');
    await expect(addServerButton).toBeVisible({ timeout: 10000 });

    // If bot is configured, clicking Add Server should show modal
    if (await addServerButton.isEnabled()) {
      await addServerButton.click();

      // Registration key modal should appear
      const modal = adminPage.locator('[role="dialog"]');
      await expect(modal).toBeVisible({ timeout: 10000 });

      // Should show registration key info
      await expect(adminPage.locator("text=Registration Key")).toBeVisible();
      await expect(adminPage.locator("text=!register")).toBeVisible();

      // Close modal by clicking X button
      const closeButton = modal.locator("button").first();
      await closeButton.click();
      await expect(modal).not.toBeVisible({ timeout: 5000 });
    }
  });

  test("channel configuration flow", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    // Navigate to guild detail page
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Should show channels table
    await expect(adminPage.locator("table")).toBeVisible({ timeout: 10000 });

    // Find first channel row
    const channelRow = adminPage.locator("tbody tr").first();
    await expect(channelRow).toBeVisible();

    // Toggle enabled state for first channel
    const enableToggle = channelRow.locator('[role="switch"]').first();
    if (await enableToggle.isVisible()) {
      const initialState = await enableToggle.getAttribute("aria-checked");
      await enableToggle.click();

      // Should update immediately
      await expect(enableToggle).toHaveAttribute(
        "aria-checked",
        initialState === "true" ? "false" : "true"
      );
    }

    // Should show unsaved changes indicator
    await expect(
      adminPage.locator("text=You have unsaved changes")
    ).toBeVisible({ timeout: 5000 });

    // Click Update to save
    const updateButton = adminPage.locator('button:has-text("Update")');
    await updateButton.click();

    // Success toast should appear
    const successToast = adminPage.locator("text=/updated/i");
    await expect(successToast).toBeVisible({ timeout: 5000 });
  });

  test("disable and reenable guild", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Find guild enabled toggle (in header)
    const guildToggle = adminPage.locator('[role="switch"]').first();
    await expect(guildToggle).toBeVisible({ timeout: 10000 });

    // Initial state should be enabled for mock guild
    await expect(guildToggle).toHaveAttribute("aria-checked", "true");

    // Disable the guild
    await guildToggle.click();
    await expect(guildToggle).toHaveAttribute("aria-checked", "false");

    // Success message should appear
    await expect(adminPage.locator("text=/disabled/i")).toBeVisible({
      timeout: 5000,
    });

    // Re-enable the guild
    await guildToggle.click();
    await expect(guildToggle).toHaveAttribute("aria-checked", "true");

    // Success message should appear
    await expect(adminPage.locator("text=/enabled/i")).toBeVisible({
      timeout: 5000,
    });
  });

  test("enable all channels flow", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Click "Enable All" button
    const enableAllButton = adminPage.locator('button:has-text("Enable All")');
    await expect(enableAllButton).toBeVisible({ timeout: 10000 });
    await enableAllButton.click();

    // All channel enabled toggles should be checked
    const rows = adminPage.locator("tbody tr");
    const rowCount = await rows.count();

    for (let i = 0; i < rowCount; i++) {
      const toggle = rows.nth(i).locator('[role="switch"]').first();
      if (await toggle.isVisible()) {
        await expect(toggle).toHaveAttribute("aria-checked", "true");
      }
    }

    // Should show unsaved changes
    await expect(
      adminPage.locator("text=You have unsaved changes")
    ).toBeVisible();
  });

  test("disable all channels flow", async ({
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

    // All channel enabled toggles should be unchecked
    const rows = adminPage.locator("tbody tr");
    const rowCount = await rows.count();

    for (let i = 0; i < rowCount; i++) {
      const toggle = rows.nth(i).locator('[role="switch"]').first();
      if (await toggle.isVisible()) {
        await expect(toggle).toHaveAttribute("aria-checked", "false");
      }
    }
  });

  test("navigate from list to detail and back", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    // Start at list page
    await gotoDiscordBotPage(adminPage);

    // Click on guild to go to detail
    const guildButton = adminPage.locator(
      `button:has-text("${mockRegisteredGuild.name}")`
    );
    await expect(guildButton).toBeVisible({ timeout: 10000 });
    await guildButton.click();

    // Should be on detail page
    await expect(adminPage).toHaveURL(
      new RegExp(`/admin/discord-bot/${mockRegisteredGuild.id}`)
    );
    await expect(adminPage.locator("text=Channel Configuration")).toBeVisible();

    // Click back button to return to list
    const backButton = adminPage.locator(
      'button:has-text("Back"), a:has-text("Back"), button[aria-label*="back" i]'
    );
    if (await backButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await backButton.click();
      await expect(adminPage).toHaveURL(/\/admin\/discord-bot$/);
    }
  });
});
