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
} from "@tests/e2e/admin/discord-bot/fixtures";

// Disable retries for Discord bot tests - attempt once at most
test.describe.configure({ retries: 0 });

test.describe("Admin Workflow E2E Flows", () => {
  test("complete setup and configuration flow", async ({
    adminPage,
    mockRegisteredGuild,
    mockBotConfigured: _mockBotConfigured,
  }) => {
    // Start at list page
    await gotoDiscordBotPage(adminPage);

    // Verify list page loads
    await expect(
      adminPage
        .locator('[aria-label="admin-page-title"]')
        .getByText("Discord Bots")
    ).toBeVisible();
    await expect(
      adminPage.locator("text=Server Configurations").first()
    ).toBeVisible();

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
    await expect(
      adminPage.locator("text=Channel Configuration").first()
    ).toBeVisible();

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

    // Save changes - wait for the bulk update API call
    // Update button is now in the header
    const updateButton = adminPage.locator(
      'button:has-text("Update Configuration")'
    );
    // Verify button is visible and enabled before clicking
    await expect(updateButton).toBeEnabled({ timeout: 5000 });

    const bulkUpdatePromise = adminPage.waitForResponse(
      (response) =>
        response
          .url()
          .includes(
            `/api/manage/admin/discord-bot/guilds/${mockRegisteredGuild.id}/channels`
          ) && response.request().method() === "PATCH"
    );

    await updateButton.click();
    await bulkUpdatePromise;

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
