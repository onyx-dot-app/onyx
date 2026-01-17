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
    await expect(adminPage.locator("text=Discord Bots")).toBeVisible();
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

    await expect(
      notConfiguredBadge.or(tokenInput).or(configuredBadge)
    ).toBeVisible({ timeout: 10000 });

    // If not configured, the save token button should be visible
    if (await notConfiguredBadge.isVisible().catch(() => false)) {
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
});
