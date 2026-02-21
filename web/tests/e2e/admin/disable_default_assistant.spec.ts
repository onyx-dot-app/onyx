import { test, expect, Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { createAssistant } from "@tests/e2e/utils/assistantUtils";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const MAX_SETTING_SAVE_ATTEMPTS = 5;
const SETTING_SAVE_RETRY_DELAY_MS = 750;

/**
 * Expand the "Advanced Options" collapsible section on the Chat Preferences page.
 * The section is closed by default (`defaultOpen={false}`).
 * Only expands if not already open (checks for the switch element visibility).
 */
async function expandAdvancedOptions(page: Page): Promise<void> {
  // Wait for the page title to be visible, signalling the form has loaded
  await expect(page.locator('[aria-label="admin-page-title"]')).toBeVisible({
    timeout: 10000,
  });

  // Check if the switch is already visible (section already expanded)
  const switchEl = page.locator("#disable_default_assistant");
  const alreadyVisible = await switchEl.isVisible().catch(() => false);
  if (alreadyVisible) return;

  const header = page.getByText("Advanced Options", { exact: true });
  await expect(header).toBeVisible({ timeout: 10000 });
  await header.scrollIntoViewIfNeeded();
  await header.click();

  // Wait for the collapsible content to expand and switch to appear
  await expect(switchEl).toBeVisible({ timeout: 5000 });
}

/**
 * Toggle the "Always Start with an Agent" setting (formerly "Disable Default Assistant")
 * on the Chat Preferences page. Uses auto-save via the SwitchField.
 *
 * The switch is a SwitchField with name="disable_default_assistant" which renders
 * `<button role="switch" id="disable_default_assistant" aria-checked="...">`.
 */
async function setDisableDefaultAssistantSetting(
  page: Page,
  isDisabled: boolean
): Promise<void> {
  let lastCheckedState = false;

  for (let attempt = 0; attempt < MAX_SETTING_SAVE_ATTEMPTS; attempt += 1) {
    await page.goto("/admin/configuration/chat-preferences");
    await page.waitForLoadState("networkidle");

    // Expand "Advanced Options" collapsible (closed by default)
    await expandAdvancedOptions(page);

    const switchEl = page.locator("#disable_default_assistant");
    await expect(switchEl).toBeVisible({ timeout: 5000 });

    const currentState = await switchEl.getAttribute("aria-checked");
    lastCheckedState = currentState === "true";

    if (lastCheckedState === isDisabled) {
      return;
    }

    // Toggle the switch
    await switchEl.click();

    // Wait for auto-save toast
    await expect(page.getByText("Settings updated")).toBeVisible({
      timeout: 5000,
    });

    await page.waitForTimeout(SETTING_SAVE_RETRY_DELAY_MS);

    // Verify persistence after reload
    await page.reload();
    await page.waitForLoadState("networkidle");

    // Re-expand Advanced Options (closed by default after reload)
    await expandAdvancedOptions(page);

    const newState = await switchEl.getAttribute("aria-checked");
    lastCheckedState = newState === "true";

    if (lastCheckedState === isDisabled) {
      return;
    }
  }

  throw new Error(
    `Failed to persist Always Start with an Agent setting after ${MAX_SETTING_SAVE_ATTEMPTS} attempts (expected ${isDisabled}, last=${lastCheckedState}).`
  );
}

test.describe("Disable Default Assistant Setting @exclusive", () => {
  let createdAssistantId: number | null = null;

  test.beforeEach(async ({ page }) => {
    // Log in as admin
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test.afterEach(async ({ page }) => {
    // Clean up any assistant created during the test
    if (createdAssistantId !== null) {
      const client = new OnyxApiClient(page.request);
      await client.deleteAssistant(createdAssistantId);
      createdAssistantId = null;
    }

    // Ensure default assistant is enabled (switch unchecked) after each test
    // to avoid interfering with other tests
    await setDisableDefaultAssistantSetting(page, false);
  });

  test("admin can enable and disable the setting in chat preferences", async ({
    page,
  }) => {
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

    // Store for cleanup
    if (assistantIdMatch) {
      createdAssistantId = Number(assistantIdMatch[1]);
    }

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

  test("chat preferences shows disabled state when setting is enabled", async ({
    page,
  }) => {
    // First enable the setting
    await setDisableDefaultAssistantSetting(page, true);

    // Navigate to chat preferences configuration page
    await page.goto("/admin/configuration/chat-preferences");
    await page.waitForLoadState("networkidle");

    // Wait for the page to fully render (page title signals form is loaded)
    await expect(page.locator('[aria-label="admin-page-title"]')).toHaveText(
      "Chat Preferences",
      { timeout: 10000 }
    );

    // The new page wraps Connectors + Actions & Tools in <Disabled disabled={values.disable_default_assistant}>
    // When disabled, the section should have reduced opacity / disabled styling
    // The "Modify Prompt" button should still be accessible (it's outside the Disabled wrapper)
    // Use text locator (Opal Button wraps text in Interactive.Base > Slot which may
    // not expose role="button" to Playwright's getByRole)
    await expect(page.getByText("Modify Prompt")).toBeVisible({
      timeout: 5000,
    });

    // The "Actions & Tools" section text should still be present but visually disabled
    await expect(page.getByText("Actions & Tools")).toBeVisible();
  });

  test("chat preferences shows full configuration UI when setting is disabled", async ({
    page,
  }) => {
    // Ensure setting is disabled
    await setDisableDefaultAssistantSetting(page, false);

    // Navigate to chat preferences configuration page
    await page.goto("/admin/configuration/chat-preferences");
    await page.waitForLoadState("networkidle");

    // Verify configuration UI is shown (Actions & Tools section should be visible and enabled)
    await expect(page.getByText("Actions & Tools")).toBeVisible({
      timeout: 10000,
    });

    // Verify the page title
    await expect(page.locator('[aria-label="admin-page-title"]')).toHaveText(
      "Chat Preferences"
    );
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
});
