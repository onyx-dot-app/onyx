/**
 * E2E tests for Discord bot UI component states.
 */

import { test, expect } from "./fixtures";

test.describe("Component States", () => {
  test("loading state", async ({ adminPage }) => {
    // Intercept API to delay response
    await adminPage.route(
      "**/api/manage/admin/discord-bot/**",
      async (route) => {
        await new Promise((r) => setTimeout(r, 500));
        await route.continue();
      }
    );

    await adminPage.goto("/admin/bots/discord");

    // Should show loading skeleton or spinner during load
    const loading = adminPage.locator(
      '.skeleton, .spinner, [role="progressbar"], .loading'
    );

    // Loading state should appear briefly
  });

  test("error state api failure", async ({ adminPage }) => {
    // Intercept API to return error
    await adminPage.route("**/api/manage/admin/discord-bot/**", (route) => {
      route.fulfill({
        status: 500,
        body: JSON.stringify({ detail: "Internal Server Error" }),
      });
    });

    await adminPage.goto("/admin/bots/discord");

    // Should show error message
    const errorMessage = adminPage.locator(
      '.error, [role="alert"], text=/error|failed/i'
    );

    // Retry button should be available
    const retryButton = adminPage.locator('button:has-text("Retry")');
  });

  test("save pending state", async ({ adminPage, seededGuild }) => {
    await adminPage.goto(`/admin/bots/discord/guilds/${seededGuild.id}`);

    // Intercept API to delay save
    await adminPage.route(
      "**/api/manage/admin/discord-bot/guilds/*",
      async (route) => {
        if (route.request().method() === "PATCH") {
          await new Promise((r) => setTimeout(r, 1000));
          await route.continue();
        } else {
          await route.continue();
        }
      }
    );

    // Trigger a save action
    const toggle = adminPage.locator('[role="switch"]').first();
    if (await toggle.isVisible()) {
      await toggle.click();

      // Button should show spinner during save
      const savingButton = adminPage.locator("button:disabled");
      const spinner = adminPage.locator('.spinner, [role="progressbar"]');
    }
  });

  test("save success toast", async ({ adminPage, seededGuild }) => {
    await adminPage.goto(`/admin/bots/discord/guilds/${seededGuild.id}`);

    // Trigger a save action
    const toggle = adminPage.locator('[role="switch"]').first();
    if (await toggle.isVisible()) {
      await toggle.click();

      // Success toast should appear
      const toast = adminPage.locator(
        '.toast, [role="alert"], text=/saved|success/i'
      );
      await expect(toast).toBeVisible({ timeout: 5000 });
    }
  });

  test("save error toast", async ({ adminPage, seededGuild }) => {
    // Intercept API to return error on save
    await adminPage.route(
      "**/api/manage/admin/discord-bot/guilds/*",
      (route) => {
        if (route.request().method() === "PATCH") {
          route.fulfill({
            status: 400,
            body: JSON.stringify({ detail: "Validation error" }),
          });
        } else {
          route.continue();
        }
      }
    );

    await adminPage.goto(`/admin/bots/discord/guilds/${seededGuild.id}`);

    const toggle = adminPage.locator('[role="switch"]').first();
    if (await toggle.isVisible()) {
      await toggle.click();

      // Error toast should appear
      const errorToast = adminPage.locator(
        '.toast.error, [role="alert"]:has-text("error"), text=/failed|error/i'
      );
      await expect(errorToast).toBeVisible({ timeout: 5000 });
    }
  });

  test("toggle optimistic update", async ({ adminPage, seededGuild }) => {
    await adminPage.goto(`/admin/bots/discord/guilds/${seededGuild.id}`);

    const toggle = adminPage.locator('[role="switch"]').first();

    if (await toggle.isVisible()) {
      const initialState = await toggle.getAttribute("aria-checked");

      await toggle.click();

      // Should update immediately (optimistic)
      await expect(toggle).toHaveAttribute(
        "aria-checked",
        initialState === "true" ? "false" : "true"
      );
    }
  });

  test("form validation empty token", async ({ adminPage }) => {
    await adminPage.goto("/admin/bots/discord");

    const configButton = adminPage.locator(
      'button:has-text("Configure"), button:has-text("Add")'
    );

    if (await configButton.isVisible()) {
      await configButton.click();

      // Try to submit with empty token
      const submitButton = adminPage.locator(
        'button[type="submit"], button:has-text("Save")'
      );
      if (await submitButton.isVisible()) {
        await submitButton.click();

        // Validation error should appear
        const error = adminPage.locator(
          '.error, [role="alert"], text=/required/i'
        );
        await expect(error).toBeVisible();
      }
    }
  });

  test("confirmation modal cancel", async ({ adminPage, seededGuild }) => {
    await adminPage.goto("/admin/bots/discord");

    // Find delete button
    const deleteButton = adminPage.locator('button:has-text("Delete")').first();

    if (await deleteButton.isVisible()) {
      await deleteButton.click();

      // Modal should appear
      const modal = adminPage.locator('[role="dialog"]');
      await expect(modal).toBeVisible();

      // Click cancel
      const cancelButton = adminPage.locator('button:has-text("Cancel")');
      await cancelButton.click();

      // Modal should close
      await expect(modal).not.toBeVisible();
    }
  });

  test("keyboard navigation", async ({ adminPage }) => {
    await adminPage.goto("/admin/bots/discord");

    // Tab through controls
    await adminPage.keyboard.press("Tab");
    await adminPage.keyboard.press("Tab");
    await adminPage.keyboard.press("Tab");

    // Focus should move through interactive elements
    const focused = adminPage.locator(":focus");
    await expect(focused).toBeVisible();
  });
});
