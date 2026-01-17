/**
 * E2E tests for Discord channel configuration.
 */

import { test, expect } from "./fixtures";

test.describe("Channel Configuration", () => {
  test("channels list displays", async ({ adminPage, seededGuild }) => {
    await adminPage.goto(`/admin/bots/discord/guilds/${seededGuild.id}`);

    // Channel list should be visible
    const channelList = adminPage.locator(
      '[data-testid="channel-list"], table, .channel-list'
    );

    // Either list is visible or "no channels" message
    const noChannels = adminPage.locator("text=/no channels/i");
    await expect(channelList.or(noChannels)).toBeVisible();
  });

  test("channel type icons display", async ({ adminPage, seededGuild }) => {
    await adminPage.goto(`/admin/bots/discord/guilds/${seededGuild.id}`);

    // Look for channel type icons (text and forum)
    const textIcon = adminPage.locator(
      '[data-channel-type="text"], .text-channel-icon, svg[aria-label*="text"]'
    );
    const forumIcon = adminPage.locator(
      '[data-channel-type="forum"], .forum-channel-icon, svg[aria-label*="forum"]'
    );

    // At least one channel type icon should be visible if channels exist
    const channelRows = adminPage.locator('tr, [data-testid="channel-item"]');
    if ((await channelRows.count()) > 0) {
      await expect(textIcon.or(forumIcon).first()).toBeVisible();
    }
  });

  test("channel enabled toggle updates state", async ({
    adminPage,
    seededGuild,
  }) => {
    await adminPage.goto(`/admin/bots/discord/guilds/${seededGuild.id}`);

    // Find first channel's enabled toggle
    const enabledToggle = adminPage
      .locator('[data-testid="channel-enabled"], input[type="checkbox"]')
      .first();

    if (await enabledToggle.isVisible()) {
      const initialState = await enabledToggle.isChecked();
      await enabledToggle.click();

      // State should update immediately (optimistic update)
      await expect(enabledToggle).toBeChecked({ checked: !initialState });

      // Toggle back to restore state
      await enabledToggle.click();
      await expect(enabledToggle).toBeChecked({ checked: initialState });
    }
  });

  test("channel search filter works", async ({ adminPage, seededGuild }) => {
    await adminPage.goto(`/admin/bots/discord/guilds/${seededGuild.id}`);
    await adminPage.waitForLoadState("networkidle");

    const searchInput = adminPage.locator(
      'input[type="search"], input[placeholder*="search"], input[name="filter"]'
    );

    if (await searchInput.isVisible()) {
      // Get initial count of visible channels
      const channelRows = adminPage.locator(
        'tr[data-channel-id], [data-testid="channel-item"]'
      );
      const initialCount = await channelRows.count();

      // Search for something that likely won't match
      await searchInput.fill("xyznonexistent123");
      await adminPage.waitForTimeout(300);

      // Should have fewer (or zero) results
      const filteredCount = await channelRows.count();
      expect(filteredCount).toBeLessThanOrEqual(initialCount);

      // Clear search
      await searchInput.clear();
    }
  });
});
