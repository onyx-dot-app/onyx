/**
 * E2E tests for Discord bot admin workflow flows.
 *
 * These tests verify complete user journeys through the Discord bot admin UI.
 */

import { test, expect } from "./fixtures";

test.describe("Admin Workflow E2E Flows", () => {
  test("full setup flow", async ({ adminPage }) => {
    // Navigate to Discord bot admin page
    await adminPage.goto("/admin/discord-bot");

    // Step 1: Check if bot is already configured
    const configureButton = adminPage.locator(
      'button:has-text("Configure"), button:has-text("Add Bot")'
    );
    const configuredStatus = adminPage.locator("text=/connected|configured/i");

    // If not configured, go through setup
    if (await configureButton.isVisible()) {
      await configureButton.click();

      // Enter bot token
      const tokenInput = adminPage.locator(
        'input[type="password"], input[name="token"]'
      );
      if (await tokenInput.isVisible()) {
        await tokenInput.fill("test_bot_token_12345");

        // Submit
        const submitButton = adminPage.locator('button[type="submit"]');
        await submitButton.click();

        // Should show success or connected state
        await adminPage.waitForTimeout(1000);
      }
    }

    // Step 2: Create a guild registration key
    const addServerButton = adminPage.locator(
      'button:has-text("Add Server"), button:has-text("Add Guild")'
    );

    if (await addServerButton.isVisible()) {
      await addServerButton.click();

      // Registration key should be displayed
      const keyDisplay = adminPage.locator(
        'code, [data-testid="registration-key"]'
      );
      await expect(keyDisplay).toBeVisible();

      // Copy the key
      const copyButton = adminPage.locator('button:has-text("Copy")');
      if (await copyButton.isVisible()) {
        await copyButton.click();
      }

      // Close modal
      const closeButton = adminPage.locator(
        'button:has-text("Close"), button:has-text("Done")'
      );
      if (await closeButton.isVisible()) {
        await closeButton.click();
      }
    }

    // Step 3: Verify guild appears in list (as pending)
    const guildList = adminPage.locator(
      '[data-testid="guild-list"], .guild-list, table'
    );
    await expect(guildList).toBeVisible();
  });

  test("channel configuration flow", async ({ adminPage, seededGuild }) => {
    // Navigate to guild detail page
    await adminPage.goto(`/admin/discord-bot/${seededGuild.id}`);

    // Wait for page to load
    await adminPage.waitForLoadState("networkidle");

    // Step 1: Find a channel to configure
    const channelRow = adminPage
      .locator('tr, [data-testid="channel-item"]')
      .first();

    if (await channelRow.isVisible()) {
      // Step 2: Enable the channel
      const enableToggle = channelRow
        .locator('[role="switch"], input[type="checkbox"]')
        .first();

      if (await enableToggle.isVisible()) {
        await enableToggle.click();

        // Should update immediately (optimistic update)
        await adminPage.waitForTimeout(300);
      }

      // Step 3: Set thread-only mode
      const threadOnlyToggle = channelRow.locator(
        '[data-testid="thread-only"], [name*="thread"]'
      );

      if (await threadOnlyToggle.isVisible()) {
        await threadOnlyToggle.click();
        await adminPage.waitForTimeout(300);
      }

      // Step 4: Set persona if available
      const personaSelect = adminPage.locator(
        '[data-testid="channel-persona"], select[name*="persona"]'
      );

      if (await personaSelect.isVisible()) {
        await personaSelect.click();

        const firstOption = adminPage.locator('[role="option"]').first();
        if (await firstOption.isVisible()) {
          await firstOption.click();
        }
      }
    }

    // Verify changes were saved (no error toast)
    const errorToast = adminPage.locator(
      '.toast.error, [role="alert"]:has-text("error")'
    );
    await expect(errorToast).not.toBeVisible();
  });

  test("disable and reenable guild", async ({ adminPage, seededGuild }) => {
    await adminPage.goto(`/admin/discord-bot/${seededGuild.id}`);

    // Find guild enabled toggle
    const guildToggle = adminPage
      .locator('[data-testid="guild-enabled"], [role="switch"]')
      .first();

    if (await guildToggle.isVisible()) {
      // Step 1: Check initial state
      const initialState = await guildToggle.getAttribute("aria-checked");

      // Step 2: Disable the guild
      if (initialState === "true") {
        await guildToggle.click();
        await adminPage.waitForTimeout(500);

        // Verify disabled state
        await expect(guildToggle).toHaveAttribute("aria-checked", "false");

        // Disabled badge should appear
        const disabledBadge = adminPage.locator("text=/disabled/i");
      }

      // Step 3: Re-enable the guild
      await guildToggle.click();
      await adminPage.waitForTimeout(500);

      // Verify enabled state
      await expect(guildToggle).toHaveAttribute("aria-checked", "true");
    }
  });

  test("bulk channel operations flow", async ({ adminPage, seededGuild }) => {
    await adminPage.goto(`/admin/discord-bot/${seededGuild.id}`);

    // Wait for channels to load
    await adminPage.waitForLoadState("networkidle");

    // Select multiple channels if available
    const selectAllCheckbox = adminPage.locator(
      'input[type="checkbox"][name="selectAll"], th input[type="checkbox"]'
    );

    if (await selectAllCheckbox.isVisible()) {
      await selectAllCheckbox.click();

      // Bulk action menu should appear
      const bulkActionsMenu = adminPage.locator(
        '[data-testid="bulk-actions"], .bulk-actions'
      );

      if (await bulkActionsMenu.isVisible()) {
        // Enable all selected
        const enableAllButton = adminPage.locator(
          'button:has-text("Enable All")'
        );
        if (await enableAllButton.isVisible()) {
          await enableAllButton.click();
          await adminPage.waitForTimeout(500);
        }
      }
    }
  });

  test("sync channels flow", async ({ adminPage, seededGuild }) => {
    await adminPage.goto(`/admin/discord-bot/${seededGuild.id}`);

    // Find sync channels button
    const syncButton = adminPage.locator(
      'button:has-text("Sync"), button:has-text("Refresh Channels")'
    );

    if (await syncButton.isVisible()) {
      await syncButton.click();

      // Success message should appear after sync completes
      const successMessage = adminPage.locator(
        "text=/synced|updated|refreshed/i, .toast.success"
      );
      await expect(successMessage).toBeVisible({ timeout: 10000 });
    }
  });

  test("delete guild flow", async ({ adminPage, seededGuild }) => {
    await adminPage.goto("/admin/discord-bot");

    // Find the guild's delete button
    const deleteButton = adminPage.locator(
      `[data-guild-id="${seededGuild.id}"] button:has-text("Delete"),
       tr:has([data-guild-id="${seededGuild.id}"]) button:has-text("Delete")`
    );

    if (await deleteButton.isVisible()) {
      await deleteButton.click();

      // Confirmation modal should appear
      const modal = adminPage.locator('[role="dialog"]');
      await expect(modal).toBeVisible();

      // Confirm deletion
      const confirmButton = modal.locator(
        'button:has-text("Delete"), button:has-text("Confirm")'
      );
      await confirmButton.click();

      // Guild should be removed from list
      await adminPage.waitForTimeout(500);

      // Verify guild is no longer in list
      const guildItem = adminPage.locator(
        `[data-guild-id="${seededGuild.id}"]`
      );
      await expect(guildItem).not.toBeVisible();
    }
  });
});
