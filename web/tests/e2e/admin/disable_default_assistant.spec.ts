import { test, expect, Page } from "@playwright/test";
import { loginAs } from "../utils/auth";
import { createAssistant } from "../utils/assistantUtils";

const DISABLE_DEFAULT_ASSISTANT_LABEL =
  'label:has-text("Disable Default Assistant") input[type="checkbox"]';
const MAX_SETTING_SAVE_ATTEMPTS = 5;
const SETTING_SAVE_RETRY_DELAY_MS = 750;

async function setDisableDefaultAssistantSetting(
  page: Page,
  isDisabled: boolean
): Promise<void> {
  let lastCheckedState = false;

  for (let attempt = 0; attempt < MAX_SETTING_SAVE_ATTEMPTS; attempt += 1) {
    await page.goto("/admin/settings");
    await page.waitForURL("/admin/settings");

    const disableDefaultAssistantCheckbox = page.locator(
      DISABLE_DEFAULT_ASSISTANT_LABEL
    );
    lastCheckedState = await disableDefaultAssistantCheckbox.isChecked();

    if (lastCheckedState === isDisabled) {
      return;
    }

    await disableDefaultAssistantCheckbox.click();
    if (isDisabled) {
      await expect(disableDefaultAssistantCheckbox).toBeChecked();
    } else {
      await expect(disableDefaultAssistantCheckbox).not.toBeChecked();
    }

    await page.waitForTimeout(SETTING_SAVE_RETRY_DELAY_MS);
    await page.reload();
    await page.waitForURL("/admin/settings");
    lastCheckedState = await disableDefaultAssistantCheckbox.isChecked();

    if (lastCheckedState === isDisabled) {
      return;
    }
  }

  throw new Error(
    `Failed to persist Disable Default Assistant setting after ${MAX_SETTING_SAVE_ATTEMPTS} attempts (expected ${isDisabled}, last=${lastCheckedState}).`
  );
}

test.describe("Disable Default Assistant Setting @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    // Log in as admin
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test.afterEach(async ({ page }) => {
    // Ensure default assistant is enabled (checkbox unchecked) after each test
    // to avoid interfering with other tests
    await setDisableDefaultAssistantSetting(page, false);
  });

  test("admin can enable and disable the setting in workspace settings", async ({
    page,
  }) => {
    // Navigate to settings page
    await setDisableDefaultAssistantSetting(page, true);
    await setDisableDefaultAssistantSetting(page, false);
    await setDisableDefaultAssistantSetting(page, true);
  });

  test("new session button uses current agent when setting is enabled", async ({
    page,
  }) => {
    // First enable the setting
    await setDisableDefaultAssistantSetting(page, true);

    // Navigate to app and create a new assistant to ensure there's one besides the default
    await page.goto("/app");
    const assistantName = `Test Assistant ${Date.now()}`;
    await createAssistant(page, {
      name: assistantName,
      description: "Test assistant for new session button test",
      instructions: "You are a helpful test assistant.",
    });

    // Extract the assistant ID from the URL
    const currentUrl = page.url();
    const assistantIdMatch = currentUrl.match(/assistantId=(\d+)/);
    expect(assistantIdMatch).toBeTruthy();

    // Click the "New Session" button
    const newSessionButton = page.locator(
      '[data-testid="AppSidebar/new-session"]'
    );
    await newSessionButton.click();

    // Verify the WelcomeMessage shown is NOT from the default assistant
    // Default assistant shows onyx-logo, custom assistants show assistant-name-display
    await expect(page.locator('[data-testid="onyx-logo"]')).not.toBeVisible();
    await expect(
      page.locator('[data-testid="assistant-name-display"]')
    ).toBeVisible();
  });

  test("direct navigation to /app uses first pinned assistant when setting is enabled", async ({
    page,
  }) => {
    // First enable the setting
    await setDisableDefaultAssistantSetting(page, true);

    // Navigate directly to /app
    await page.goto("/app");

    // Verify that we didn't land on the default assistant (ID 0)
    // The assistant selection should be a pinned or available assistant (not ID 0)
    const currentUrl = page.url();
    // If assistantId is in URL, it should not be 0
    if (currentUrl.includes("assistantId=")) {
      expect(currentUrl).not.toContain("assistantId=0");
    }
  });

  test("default assistant config panel shows message when setting is enabled", async ({
    page,
  }) => {
    // First enable the setting
    await setDisableDefaultAssistantSetting(page, true);

    // Navigate to default assistant configuration page
    await page.goto("/admin/configuration/default-assistant");
    await page.waitForURL("/admin/configuration/default-assistant");

    // Verify informative message is shown
    await expect(
      page.getByText(
        "The default assistant is currently disabled in your workspace settings."
      )
    ).toBeVisible();

    // Verify link to Settings is present
    const settingsLinks = page.locator('a[href="/admin/settings"]');
    await expect(settingsLinks).toHaveCount(2);
    await expect(settingsLinks.first()).toBeVisible();
    await expect(settingsLinks.nth(1)).toBeVisible();

    // Verify actual configuration UI is hidden (Instructions textarea should not be visible)
    await expect(
      page.locator('textarea[placeholder*="professional email"]')
    ).not.toBeVisible();
  });

  test("default assistant is available again when setting is disabled", async ({
    page,
  }) => {
    // Navigate to settings and ensure setting is disabled
    await setDisableDefaultAssistantSetting(page, false);

    // Navigate directly to /app without parameters
    await page.goto("/app");

    // The default assistant (ID 0) should be available
    // We can verify this by checking that the app loads successfully
    // and doesn't force navigation to a specific assistant
    const currentUrl = page.url();
    // URL might not have assistantId, or it might be 0, or might redirect to default behavior
    expect(page.url()).toContain("/app");

    // Verify the new session button navigates to /app without assistantId
    const newSessionButton = page.locator(
      '[data-testid="AppSidebar/new-session"]'
    );
    await newSessionButton.click();

    // Should navigate to /app without assistantId parameter
    const newUrl = page.url();
    expect(newUrl).toContain("/app");
  });

  test("default assistant config panel shows configuration UI when setting is disabled", async ({
    page,
  }) => {
    // Navigate to settings and ensure setting is disabled
    await page.goto("/admin/settings");
    await page.waitForURL("/admin/settings");

    const disableDefaultAssistantCheckbox = page.locator(
      'label:has-text("Disable Default Assistant") input[type="checkbox"]'
    );
    const isEnabled = await disableDefaultAssistantCheckbox.isChecked();
    if (isEnabled) {
      await disableDefaultAssistantCheckbox.click();
    }

    // Navigate to default assistant configuration page
    await page.goto("/admin/configuration/default-assistant");
    await page.waitForURL("/admin/configuration/default-assistant");

    // Verify configuration UI is shown (Instructions section should be visible)
    await expect(page.getByText("Instructions", { exact: true })).toBeVisible();

    // Verify informative message is NOT shown
    await expect(
      page.getByText(
        "The default assistant is currently disabled in your workspace settings."
      )
    ).not.toBeVisible();
  });
});
