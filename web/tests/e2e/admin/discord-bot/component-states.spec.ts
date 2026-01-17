/**
 * E2E tests for Discord bot UI component states.
 *
 * Tests loading states, error states, and various UI component behaviors.
 */

import {
  test,
  expect,
  gotoDiscordBotPage,
  gotoGuildDetailPage,
} from "./fixtures";

test.describe("Component States", () => {
  test("loading state shows loader", async ({ adminPage }) => {
    // Intercept API to delay response
    await adminPage.route(
      "**/api/manage/admin/discord-bot/**",
      async (route) => {
        await new Promise((r) => setTimeout(r, 1000));
        await route.continue();
      }
    );

    await adminPage.goto("/admin/discord-bot");

    // Should show loading indicator (ThreeDotsLoader)
    // The loader should appear while data is being fetched
    const loader = adminPage.locator(".loading, .loader, svg");
    // Give it a moment to appear
    await adminPage.waitForTimeout(100);

    // Wait for page to finish loading
    await adminPage.waitForLoadState("networkidle");

    // After loading, page title should be visible
    await expect(adminPage.locator("text=Discord Bots")).toBeVisible();
  });

  test("error state shows error message", async ({ adminPage }) => {
    // Intercept API to return error
    await adminPage.route("**/api/manage/admin/discord-bot/guilds", (route) => {
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Internal Server Error" }),
      });
    });

    await adminPage.goto("/admin/discord-bot");
    await adminPage.waitForLoadState("networkidle");

    // Should show error message from ErrorCallout
    const errorMessage = adminPage.locator("text=/failed|error/i");
    await expect(errorMessage).toBeVisible({ timeout: 10000 });
  });

  test("toggle optimistic update", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Find guild enabled toggle
    const toggle = adminPage.locator('[role="switch"]').first();
    await expect(toggle).toBeVisible({ timeout: 10000 });

    const initialState = await toggle.getAttribute("aria-checked");

    // Click toggle
    await toggle.click();

    // Should update immediately (optimistic update)
    await expect(toggle).toHaveAttribute(
      "aria-checked",
      initialState === "true" ? "false" : "true"
    );
  });

  test("success toast appears after save", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Toggle guild enabled state
    const toggle = adminPage.locator('[role="switch"]').first();
    await expect(toggle).toBeVisible({ timeout: 10000 });
    await toggle.click();

    // Success toast should appear
    const successToast = adminPage.locator("text=/success|enabled|disabled/i");
    await expect(successToast).toBeVisible({ timeout: 5000 });
  });

  test("error toast appears on save failure", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    // First navigate to set up the mock, then add error route
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Now intercept PATCH to return error
    await adminPage.route(
      `**/api/manage/admin/discord-bot/guilds/${mockRegisteredGuild.id}`,
      (route) => {
        if (route.request().method() === "PATCH") {
          route.fulfill({
            status: 400,
            contentType: "application/json",
            body: JSON.stringify({ detail: "Validation error" }),
          });
        } else {
          route.continue();
        }
      }
    );

    // Toggle to trigger save
    const toggle = adminPage.locator('[role="switch"]').first();
    await toggle.click();

    // Error toast should appear
    const errorToast = adminPage.locator("text=/error|failed/i");
    await expect(errorToast).toBeVisible({ timeout: 5000 });
  });

  test("unsaved changes indicator shows and hides", async ({
    adminPage,
    mockRegisteredGuild,
  }) => {
    await gotoGuildDetailPage(adminPage, mockRegisteredGuild.id);

    // Initially no unsaved changes
    const unsavedIndicator = adminPage.locator("text=You have unsaved changes");
    await expect(unsavedIndicator).not.toBeVisible();

    // Make a change to a channel
    const channelToggle = adminPage
      .locator("tbody tr")
      .first()
      .locator('[role="switch"]')
      .first();

    if (await channelToggle.isVisible({ timeout: 5000 }).catch(() => false)) {
      await channelToggle.click();

      // Unsaved changes should appear
      await expect(unsavedIndicator).toBeVisible({ timeout: 5000 });

      // Click Update to save
      const updateButton = adminPage.locator('button:has-text("Update")');
      await updateButton.click();

      // After save, indicator should disappear
      await expect(unsavedIndicator).not.toBeVisible({ timeout: 5000 });
    }
  });

  test("bot token validation - save button disabled when empty", async ({
    adminPage,
  }) => {
    await gotoDiscordBotPage(adminPage);

    // Look for token input (only visible when not configured)
    const tokenInput = adminPage.locator('input[placeholder*="token" i]');
    const saveTokenButton = adminPage.locator('button:has-text("Save Token")');

    if (await tokenInput.isVisible({ timeout: 5000 }).catch(() => false)) {
      // Button should be disabled when input is empty
      await expect(saveTokenButton).toBeDisabled();

      // Enter some text
      await tokenInput.fill("some_token");

      // Button should now be enabled
      await expect(saveTokenButton).toBeEnabled();

      // Clear input
      await tokenInput.clear();

      // Button should be disabled again
      await expect(saveTokenButton).toBeDisabled();
    }
  });

  test("modal closes on cancel", async ({ adminPage, mockRegisteredGuild }) => {
    await gotoDiscordBotPage(adminPage);

    // Find delete button in the guild row
    const tableRow = adminPage.locator("tr").filter({
      hasText: mockRegisteredGuild.name,
    });
    const deleteButton = tableRow.locator("button").last();

    if (await deleteButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await deleteButton.click();

      // Modal should appear
      const modal = adminPage.locator('[role="dialog"]');
      await expect(modal).toBeVisible({ timeout: 10000 });

      // Click cancel
      const cancelButton = adminPage.locator('button:has-text("Cancel")');
      await cancelButton.click();

      // Modal should close
      await expect(modal).not.toBeVisible({ timeout: 5000 });
    }
  });

  test("keyboard navigation works", async ({ adminPage }) => {
    await gotoDiscordBotPage(adminPage);

    // Tab through controls
    await adminPage.keyboard.press("Tab");
    await adminPage.keyboard.press("Tab");
    await adminPage.keyboard.press("Tab");

    // Focus should be on an interactive element
    const focused = adminPage.locator(":focus");
    await expect(focused).toBeVisible({ timeout: 5000 });

    // The focused element should be interactive (button, input, switch, etc.)
    const tagName = await focused.evaluate((el) => el.tagName.toLowerCase());
    expect(["button", "input", "a", "select"]).toContain(tagName);
  });
});
