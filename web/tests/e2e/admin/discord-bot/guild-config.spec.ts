/**
 * E2E tests for Discord guild detail/config page.
 *
 * Tests the guild configuration page which shows:
 * - Guild enabled/disabled toggle
 * - Default Agent (persona) selector
 * - Channel Configuration section
 */

import { test, expect, gotoGuildDetailPage } from "./fixtures";

test.describe("Guild Configuration Page", () => {
  test("guild detail page loads", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Page should load with guild info
    await expect(adminPage).toHaveURL(
      new RegExp(`/admin/discord-bot/${mockRegisteredGuild.id}`)
    );

    // Should show the guild name in the header
    await expect(
      adminPage.locator(`text=${mockRegisteredGuild.name}`)
    ).toBeVisible();
  });

  test("guild enabled toggle visible", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Find the enabled toggle in the header area
    const enabledLabel = adminPage.locator("text=Enabled");
    await expect(enabledLabel).toBeVisible({ timeout: 10000 });

    // The switch should be next to the label
    const enabledToggle = adminPage.locator('[role="switch"]').first();
    await expect(enabledToggle).toBeVisible();

    // Should be enabled (checked) for our mock guild
    await expect(enabledToggle).toHaveAttribute("aria-checked", "true");
  });

  test("guild enabled toggle updates state", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Find enabled toggle
    const enabledToggle = adminPage.locator('[role="switch"]').first();
    await expect(enabledToggle).toBeVisible({ timeout: 10000 });

    // Get initial state
    const initialState = await enabledToggle.getAttribute("aria-checked");

    // Click to toggle
    await enabledToggle.click();

    // State should change (optimistic update)
    await expect(enabledToggle).toHaveAttribute(
      "aria-checked",
      initialState === "true" ? "false" : "true"
    );
  });

  test("guild default agent dropdown shows options", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Should show "Default Agent" section
    await expect(adminPage.locator("text=Default Agent")).toBeVisible({
      timeout: 10000,
    });

    // Find the persona/agent dropdown (InputSelect)
    const agentDropdown = adminPage.locator(
      'button:has-text("Default Assistant")'
    );

    if (await agentDropdown.isVisible({ timeout: 5000 }).catch(() => false)) {
      await agentDropdown.click();

      // Dropdown should show available options
      const options = adminPage.locator('[role="option"]');
      await expect(options.first()).toBeVisible({ timeout: 5000 });
    }
  });

  test("guild shows channel configuration section", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Should show Channel Configuration section
    await expect(adminPage.locator("text=Channel Configuration")).toBeVisible({
      timeout: 10000,
    });

    // Should show action buttons
    await expect(
      adminPage.locator('button:has-text("Enable All")')
    ).toBeVisible();
    await expect(
      adminPage.locator('button:has-text("Disable All")')
    ).toBeVisible();
    await expect(adminPage.locator('button:has-text("Update")')).toBeVisible();
  });
});
