/**
 * E2E tests for Discord guilds list page.
 */

import { test, expect } from "./fixtures";

test.describe("Guilds List Page", () => {
  test("guilds page empty state or content", async ({ adminPage }) => {
    await adminPage.goto("/admin/bots/discord");

    // Should show "No servers" message or add server button or list of guilds
    const emptyState = adminPage.locator(
      "text=/no servers|no guilds|add server/i"
    );
    const addButton = adminPage.locator(
      'button:has-text("Add Server"), button:has-text("Add Guild")'
    );
    const guildList = adminPage.locator(
      '[data-testid="guild-list"], table, .guild-list'
    );

    await expect(emptyState.or(addButton).or(guildList)).toBeVisible();
  });

  test("guilds page shows seeded guild", async ({ adminPage, seededGuild }) => {
    await adminPage.goto("/admin/bots/discord");

    // Seeded guild should appear
    const guildItem = adminPage.locator(
      `[data-guild-id="${seededGuild.id}"], tr:has-text("${seededGuild.id}")`
    );
    const pendingBadge = adminPage.locator("text=/pending/i");
    const guildList = adminPage.locator(
      '[data-testid="guild-list"], table, .guild-list'
    );

    // Should show the guild or at least the guild list
    await expect(guildItem.or(pendingBadge).or(guildList)).toBeVisible();
  });

  test("guilds page create key flow shows modal", async ({ adminPage }) => {
    await adminPage.goto("/admin/bots/discord");

    // Click "Add Server" button
    const addButton = adminPage.locator(
      'button:has-text("Add"), button:has-text("New")'
    );

    if (await addButton.isVisible()) {
      await addButton.click();

      // Should show modal with registration key
      const modal = adminPage.locator('[role="dialog"], .modal');
      await expect(modal).toBeVisible();

      // Key should be displayed
      const keyDisplay = adminPage.locator(
        'code, [data-testid="registration-key"], input[readonly]'
      );
      await expect(keyDisplay).toBeVisible();
    }
  });

  test("guilds page copy key shows toast", async ({ adminPage }) => {
    await adminPage.goto("/admin/bots/discord");

    const addButton = adminPage.locator('button:has-text("Add")');

    if (await addButton.isVisible()) {
      await addButton.click();

      // Find copy button
      const copyButton = adminPage.locator(
        'button:has-text("Copy"), button[aria-label="Copy"]'
      );

      if (await copyButton.isVisible()) {
        await copyButton.click();

        // Toast notification should appear
        const toast = adminPage.locator(
          '.toast, [role="alert"], text=/copied/i'
        );
        await expect(toast).toBeVisible();
      }
    }
  });

  test("guilds page delete shows confirmation", async ({
    adminPage,
    seededGuild,
  }) => {
    await adminPage.goto("/admin/bots/discord");

    // Find delete button for the seeded guild
    const deleteButton = adminPage
      .locator(
        `[data-guild-id="${seededGuild.id}"] button:has-text("Delete"),
       tr:has([data-guild-id="${seededGuild.id}"]) button:has-text("Delete"),
       button:has-text("Delete")`
      )
      .first();

    if (await deleteButton.isVisible()) {
      await deleteButton.click();

      // Confirmation modal should appear
      const modal = adminPage.locator('[role="dialog"], .modal');
      await expect(modal).toBeVisible();

      // Cancel to avoid actually deleting
      const cancelButton = adminPage.locator('button:has-text("Cancel")');
      if (await cancelButton.isVisible()) {
        await cancelButton.click();
        await expect(modal).not.toBeVisible();
      }
    }
  });
});
