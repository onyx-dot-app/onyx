/**
 * E2E tests for Discord bot configuration page.
 */

import { test, expect } from "./fixtures";

test.describe("Bot Configuration Page", () => {
  test("bot config page loads", async ({ adminPage }) => {
    await adminPage.goto("/admin/bots/discord");

    // Page should load without errors
    await expect(adminPage).toHaveURL(/\/admin\/bots\/discord/);
    await expect(adminPage.locator("h1, h2, h3")).toContainText(/discord/i);
  });

  test("bot config empty state", async ({ adminPage }) => {
    await adminPage.goto("/admin/bots/discord");

    // Should show setup instructions when no bot configured
    // Look for empty state elements
    const emptyState = adminPage.locator('[data-testid="empty-state"]');
    const configButton = adminPage.locator(
      'button:has-text("Configure"), button:has-text("Setup")'
    );

    // Either empty state or config button should be visible
    await expect(
      emptyState.or(configButton).or(adminPage.locator("text=Configure"))
    ).toBeVisible();
  });

  test("bot config create flow", async ({ adminPage }) => {
    await adminPage.goto("/admin/bots/discord");

    // Click configure button if available
    const configButton = adminPage.locator(
      'button:has-text("Configure"), button:has-text("Add")'
    );

    if (await configButton.isVisible()) {
      await configButton.click();

      // Should show modal or form for entering token
      const tokenInput = adminPage.locator(
        'input[type="password"], input[name="token"], input[placeholder*="token"]'
      );
      await expect(tokenInput).toBeVisible();
    }
  });

  test("bot config shows connection status", async ({ adminPage }) => {
    await adminPage.goto("/admin/bots/discord");

    // Look for connection status indicator
    const statusIndicator = adminPage.locator(
      '[data-testid="connection-status"], .status-indicator, text=/connected|disconnected/i'
    );

    // Should have some status visible or config state
    await expect(
      statusIndicator.or(adminPage.locator("text=/configure|setup/i"))
    ).toBeVisible();
  });

  test("bot config delete confirmation", async ({ adminPage }) => {
    await adminPage.goto("/admin/bots/discord");

    // Find delete button
    const deleteButton = adminPage.locator(
      'button:has-text("Delete"), button[aria-label="Delete"]'
    );

    if (await deleteButton.isVisible()) {
      await deleteButton.click();

      // Should show confirmation modal
      const modal = adminPage.locator(
        '[role="dialog"], .modal, [data-testid="confirm-modal"]'
      );
      await expect(modal).toBeVisible();
    }
  });

  test.skip("bot config disabled in cloud", async ({ adminPage }) => {
    // This test requires cloud mode environment which is not available in e2e tests.
    // Cloud mode behavior is verified in integration tests instead.
    await adminPage.goto("/admin/bots/discord");

    // In cloud mode, config should be disabled or show env var notice
    const envNotice = adminPage.locator("text=/environment|env|managed/i");
    const configureButton = adminPage.locator(
      'button:has-text("Configure"), button:has-text("Add")'
    );

    // In cloud mode: either env notice visible OR configure button should NOT be visible
    const isEnvNoticeVisible = await envNotice.isVisible();
    const isConfigButtonVisible = await configureButton.isVisible();

    // At least one condition should be true for cloud mode
    expect(isEnvNoticeVisible || !isConfigButtonVisible).toBe(true);
  });
});
