/**
 * E2E tests for Discord bot admin workflow flows.
 *
 * These tests verify complete user journeys that span multiple pages/components.
 * Individual component tests are in their respective spec files.
 */

import {
  test,
  expect,
  gotoDiscordBotPage,
  gotoGuildDetailPage,
} from "./fixtures";

test.describe("Admin Workflow E2E Flows", () => {
  test("complete setup and configuration flow", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    // Start at list page
    await gotoDiscordBotPage(adminPage);

    // Verify list page loads
    await expect(adminPage.locator("text=Discord Bots")).toBeVisible();
    await expect(adminPage.locator("text=Server Configurations")).toBeVisible();

    // Navigate to guild detail page
    const guildButton = adminPage.locator(
      `button:has-text("${mockRegisteredGuild.name}")`
    );
    await expect(guildButton).toBeVisible({ timeout: 10000 });
    await guildButton.click();

    // Verify detail page loads
    await expect(adminPage).toHaveURL(
      new RegExp(`/admin/discord-bot/${mockRegisteredGuild.id}`)
    );
    await expect(adminPage.locator("text=Channel Configuration")).toBeVisible();

    // Configure a channel: toggle enabled, show unsaved changes, save
    const channelRow = adminPage.locator("tbody tr").first();
    await expect(channelRow).toBeVisible();

    const enableToggle = channelRow.locator('[role="switch"]').first();
    if (await enableToggle.isVisible()) {
      const initialState = await enableToggle.getAttribute("aria-checked");
      await enableToggle.click();

      await expect(enableToggle).toHaveAttribute(
        "aria-checked",
        initialState === "true" ? "false" : "true"
      );
    }

    // Verify unsaved changes indicator
    await expect(
      adminPage.locator("text=You have unsaved changes")
    ).toBeVisible({ timeout: 5000 });

    // Save changes
    const updateButton = adminPage.locator('button:has-text("Update")');
    await updateButton.click();

    // Verify success toast
    const successToast = adminPage.locator("text=/updated/i");
    await expect(successToast).toBeVisible({ timeout: 5000 });

    // Navigate back to list
    const backButton = adminPage.locator(
      'button:has-text("Back"), a:has-text("Back"), button[aria-label*="back" i]'
    );
    if (await backButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await backButton.click();
      await expect(adminPage).toHaveURL(/\/admin\/discord-bot$/);
    }
  });
});
