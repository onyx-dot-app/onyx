/**
 * E2E tests for Discord bot configuration page.
 *
 * Tests the bot token configuration card which allows admins to:
 * - Enter and save a Discord bot token
 * - View configuration status (Configured/Not Configured badge)
 * - Delete the bot token configuration
 */

import { test, expect, gotoDiscordBotPage } from "./fixtures";

// Disable retries for Discord bot tests - attempt once at most
test.describe.configure({ retries: 0 });

test.describe("Bot Configuration Page", () => {
  test("bot config page loads", async ({ adminPage }) => {
    await gotoDiscordBotPage(adminPage);

    // Page should load without errors
    await expect(adminPage).toHaveURL(/\/admin\/discord-bot/);
    // Page title should contain "Discord"
    await expect(
      adminPage
        .locator('[aria-label="admin-page-title"]')
        .getByText("Discord Bots")
    ).toBeVisible();
  });

  test("bot config shows token input when not configured", async ({
    adminPage,
  }) => {
    await gotoDiscordBotPage(adminPage);

    // When not configured, should show:
    // - "Not Configured" badge OR
    // - Token input field with "Save Token" button
    const notConfiguredBadge = adminPage.locator("text=Not Configured");
    const tokenInput = adminPage.locator('input[placeholder*="token" i]');
    const saveTokenButton = adminPage.locator('button:has-text("Save Token")');

    // Either not configured state with input, or already configured
    const configuredBadge = adminPage.locator("text=Configured").first();

    // Check that at least one of the states is visible
    // Check configured state first, then fall back to not configured state
    const isConfigured = await configuredBadge
      .isVisible({ timeout: 5000 })
      .catch(() => false);

    if (isConfigured) {
      // Bot is configured - verify configured badge is visible
      await expect(configuredBadge).toBeVisible();
    } else {
      // Bot is not configured - verify not configured badge and input are visible
      await expect(notConfiguredBadge).toBeVisible({ timeout: 10000 });
      await expect(tokenInput).toBeVisible();
      await expect(saveTokenButton).toBeVisible();
    }
  });

  test("bot config save token validation", async ({ adminPage }) => {
    await gotoDiscordBotPage(adminPage);

    const tokenInput = adminPage.locator('input[placeholder*="token" i]');
    const saveTokenButton = adminPage.locator('button:has-text("Save Token")');

    // Only run if token input is visible (not already configured)
    if (await tokenInput.isVisible({ timeout: 5000 }).catch(() => false)) {
      // Save button should be disabled when input is empty
      await expect(saveTokenButton).toBeDisabled();

      // Enter a token
      await tokenInput.fill("test_bot_token_12345");

      // Save button should now be enabled
      await expect(saveTokenButton).toBeEnabled();

      // Clear input
      await tokenInput.clear();

      // Button should be disabled again
      await expect(saveTokenButton).toBeDisabled();
    }
  });

  test("bot config shows configured state", async ({
    adminPage,
    mockBotConfigured,
  }) => {
    await gotoDiscordBotPage(adminPage);

    // With mockBotConfigured, should show configured state
    const configuredBadge = adminPage.locator("text=Configured").first();
    const deleteButton = adminPage.locator(
      'button:has-text("Delete Discord Token")'
    );

    // Should show configured badge
    await expect(configuredBadge).toBeVisible({ timeout: 10000 });

    // Should show delete button when configured
    await expect(deleteButton).toBeVisible();
  });

  test("bot config delete shows confirmation modal", async ({
    adminPage,
    mockBotConfigured,
  }) => {
    await gotoDiscordBotPage(adminPage);

    // Wait for configured state to be visible
    const configuredBadge = adminPage.locator("text=Configured").first();
    await expect(configuredBadge).toBeVisible({ timeout: 10000 });

    // Find and click delete button
    const deleteButton = adminPage.locator(
      'button:has-text("Delete Discord Token")'
    );
    await expect(deleteButton).toBeVisible();
    await deleteButton.click();

    // Confirmation modal should appear
    const modal = adminPage.locator('[role="dialog"]');
    await expect(modal).toBeVisible({ timeout: 10000 });

    // Modal should have cancel and confirm buttons
    const cancelButton = adminPage.locator('button:has-text("Cancel")');
    const confirmButton = adminPage.locator(
      'button:has-text("Delete"), button:has-text("Confirm")'
    );

    // At least one of these buttons should be visible
    await expect(cancelButton.or(confirmButton).first()).toBeVisible({
      timeout: 5000,
    });

    // Cancel to avoid actually deleting
    if (await cancelButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await cancelButton.click();
      await expect(modal).not.toBeVisible({ timeout: 5000 });
    }
  });
});
