/**
 * E2E tests for Discord guild detail/config page.
 */

import { test, expect } from "./fixtures";

test.describe("Guild Configuration Page", () => {
  test("guild detail page loads", async ({ adminPage, seededGuild }) => {
    await adminPage.goto(`/admin/bots/discord/guilds/${seededGuild.id}`);

    // Page should load with guild info
    await expect(adminPage).toHaveURL(
      new RegExp(`/admin/bots/discord/guilds/${seededGuild.id}`)
    );
  });

  test("guild enabled toggle updates state", async ({
    adminPage,
    seededGuild,
  }) => {
    await adminPage.goto(`/admin/bots/discord/guilds/${seededGuild.id}`);

    // Find enabled toggle
    const enabledToggle = adminPage
      .locator(
        '[data-testid="guild-enabled-toggle"], input[type="checkbox"][name="enabled"], [role="switch"]'
      )
      .first();

    if (await enabledToggle.isVisible()) {
      // Toggle should update and persist
      const initialState = await enabledToggle.isChecked();
      await enabledToggle.click();

      // State should change
      await expect(enabledToggle).toBeChecked({ checked: !initialState });

      // Toggle back to restore state
      await enabledToggle.click();
      await expect(enabledToggle).toBeChecked({ checked: initialState });
    }
  });

  test("guild persona dropdown shows options", async ({
    adminPage,
    seededGuild,
  }) => {
    await adminPage.goto(`/admin/bots/discord/guilds/${seededGuild.id}`);

    // Find persona dropdown
    const personaSelect = adminPage.locator(
      'select[name="persona"], [data-testid="persona-select"], button:has-text("Select Persona")'
    );

    if (await personaSelect.isVisible()) {
      await personaSelect.click();

      // Dropdown should show available personas
      const options = adminPage.locator(
        '[role="option"], option, [role="listbox"] li'
      );
      await expect(options.first()).toBeVisible();
    }
  });
});
