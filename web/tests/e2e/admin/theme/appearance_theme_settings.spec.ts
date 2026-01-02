import { test, expect, Page } from "@playwright/test";
import { loginAs, loginAsRandomUser } from "../../utils/auth";

const BASE_URL = "http://localhost:3000";

const TEST_THEME = {
  applicationName: "Acme Corp Chat",
  greetingMessage: "Welcome to Acme Corp",
  chatHeaderText: "Acme Internal Assistant",
  chatFooterText: "Powered by Acme Corp AI",
  noticeHeader: "Important Notice",
  noticeContent: "Please review our usage policy before continuing.",
  consentPrompt: "I agree to the terms and conditions",
};

/**
 * Handles the first visit notice modal - verifies content and dismisses it.
 * Only checks for consent checkbox if consentPrompt is provided.
 */
async function handleFirstVisitNotice(
  page: Page,
  expected: typeof TEST_THEME
) {
  // Wait for modal to appear
  const modal = page.getByRole("dialog");
  await expect(modal).toBeVisible({ timeout: 10000 });

  // Verify notice header
  await expect(modal.getByText(expected.noticeHeader)).toBeVisible();

  // Verify notice content
  await expect(modal.getByText(expected.noticeContent)).toBeVisible();

  // Verify consent prompt and check checkbox if consent is required
  if (expected.consentPrompt) {
    await expect(modal.getByText(expected.consentPrompt)).toBeVisible();
    const checkbox = modal.getByRole("checkbox");
    await checkbox.check();
  }

  // Click Start button to dismiss
  const startButton = modal.getByRole("button", { name: /start/i });
  await startButton.click();

  // Verify modal is dismissed
  await expect(modal).not.toBeVisible({ timeout: 5000 });
}

/**
 * Dismisses the first visit notice modal if it's visible.
 */
async function dismissModalIfVisible(page: Page, expected: typeof TEST_THEME) {
  const modal = page.getByRole("dialog");
  if (await modal.isVisible({ timeout: 2000 }).catch(() => false)) {
    await handleFirstVisitNotice(page, expected);
  }
}

/**
 * Verifies all branding elements are visible on the chat page.
 */
async function verifyChatPageBranding(page: Page, expected: typeof TEST_THEME) {
  // Verify sidebar branding - application name should be visible
  // The Logo component renders the application name in a Truncated component
  await expect(page.getByText(expected.applicationName).first()).toBeVisible({
    timeout: 10000,
  });

  // Verify greeting message on chat home
  // WelcomeMessage component renders the greeting in a Text with headingH2
  const chatIntro = page.getByTestId("chat-intro");
  await expect(chatIntro).toBeVisible();
  await expect(chatIntro.getByText(expected.greetingMessage)).toBeVisible();

  // Verify chat header text
  // AppHeader renders custom_header_content in a Text component
  await expect(page.getByText(expected.chatHeaderText)).toBeVisible();

  // Verify chat footer text
  // AppFooter renders custom_lower_disclaimer_content via MinimalMarkdown
  await expect(page.getByText(expected.chatFooterText)).toBeVisible();
}

test.describe("Appearance Theme Settings", () => {
  test.describe.serial("Theme configuration and verification", () => {
    test("Admin configures theme settings", async ({ page }) => {
      // Login as admin
      await page.context().clearCookies();
      await loginAs(page, "admin");

      // Navigate to theme settings page
      await page.goto(`${BASE_URL}/admin/theme`);
      await page.waitForLoadState("networkidle");

      // Fill Application Display Name
      const appNameInput = page.getByRole("textbox", {
        name: /application display name/i,
      });
      await appNameInput.fill(TEST_THEME.applicationName);

      // Fill Greeting Message
      const greetingInput = page.getByRole("textbox", {
        name: /greeting message/i,
      });
      await greetingInput.fill(TEST_THEME.greetingMessage);

      // Fill Chat Header Text
      const headerInput = page.getByRole("textbox", {
        name: /chat header text/i,
      });
      await headerInput.fill(TEST_THEME.chatHeaderText);

      // Fill Chat Footer Text
      const footerTextarea = page.getByRole("textbox", {
        name: /chat footer text/i,
      });
      await footerTextarea.fill(TEST_THEME.chatFooterText);

      // Enable First Visit Notice using aria-label
      const firstVisitToggle = page.getByLabel("Show First Visit Notice");
      await firstVisitToggle.click();

      // Wait for Notice Header input to appear (proves toggle worked)
      const noticeHeaderInput = page.getByRole("textbox", {
        name: /notice header/i,
      });
      await expect(noticeHeaderInput).toBeVisible({ timeout: 5000 });
      await noticeHeaderInput.fill(TEST_THEME.noticeHeader);

      // Fill Notice Content
      const noticeContentTextarea = page
        .getByPlaceholder("Add markdown content")
        .first();
      await noticeContentTextarea.fill(TEST_THEME.noticeContent);

      // Enable Require Consent using aria-label
      const consentToggle = page.getByLabel("Require Consent to Notice");
      await consentToggle.click();

      // Wait for Consent Prompt textarea to appear (proves toggle worked)
      const consentPromptTextarea = page
        .getByPlaceholder("Add markdown content")
        .last();
      await expect(consentPromptTextarea).toBeVisible({ timeout: 5000 });
      await consentPromptTextarea.fill(TEST_THEME.consentPrompt);

      // Save changes
      const saveButton = page.getByRole("button", { name: /apply changes/i });
      await saveButton.click();

      // Wait for success message
      await expect(page.getByText(/success/i)).toBeVisible({ timeout: 10000 });

      // Verify settings persisted by reloading
      await page.reload();
      await page.waitForLoadState("networkidle");

      await expect(appNameInput).toHaveValue(TEST_THEME.applicationName);
      await expect(greetingInput).toHaveValue(TEST_THEME.greetingMessage);
    });

    test("Admin sees first visit notice on chat page", async ({ page }) => {
      // Login as admin
      await page.context().clearCookies();
      // Clear the localStorage to ensure first visit notice shows
      await page.goto(BASE_URL);
      await page.evaluate(() => {
        localStorage.removeItem("allUsersInitialPopupFlowCompleted");
      });

      await loginAs(page, "admin");

      // Navigate to chat page
      await page.goto(`${BASE_URL}/chat`);
      await page.waitForLoadState("networkidle");

      // Handle and verify first visit notice
      await handleFirstVisitNotice(page, TEST_THEME);
    });

    test("Admin sees correct branding on chat page", async ({ page }) => {
      // Login as admin
      await page.context().clearCookies();
      await loginAs(page, "admin");

      // Navigate to chat page
      await page.goto(`${BASE_URL}/chat`);
      await page.waitForLoadState("networkidle");

      // Dismiss first visit notice if it appears (fresh session)
      await dismissModalIfVisible(page, TEST_THEME);

      // Verify branding
      await verifyChatPageBranding(page, TEST_THEME);
    });

    test("Admin sees correct branding on admin sidebar", async ({ page }) => {
      // Login as admin
      await page.context().clearCookies();
      await loginAs(page, "admin");

      // Navigate to admin theme page (or any admin page)
      await page.goto(`${BASE_URL}/admin/theme`);
      await page.waitForLoadState("networkidle");

      // Verify sidebar shows the custom application name
      // The sidebar uses the Logo component which displays application_name
      await expect(
        page.getByText(TEST_THEME.applicationName).first()
      ).toBeVisible({ timeout: 10000 });
    });

    test("Fresh user sees first visit notice", async ({ page }) => {
      // Clear cookies to ensure fresh state
      await page.context().clearCookies();

      // Create and login as a random new user
      await loginAsRandomUser(page);

      // The new user should be redirected to /chat after signup
      // Wait for the page to load
      await page.waitForLoadState("networkidle");

      // Handle and verify first visit notice
      await handleFirstVisitNotice(page, TEST_THEME);
    });

    test("Fresh user sees correct branding on chat page", async ({ page }) => {
      // Clear cookies to ensure fresh state
      await page.context().clearCookies();

      // Create and login as a random new user
      await loginAsRandomUser(page);

      // Wait for the page to load
      await page.waitForLoadState("networkidle");

      // Handle first visit notice if it appears
      await dismissModalIfVisible(page, TEST_THEME);

      // Navigate to chat page (in case signup redirected elsewhere)
      await page.goto(`${BASE_URL}/chat`);
      await page.waitForLoadState("networkidle");

      // Handle first visit notice again if it appears
      await dismissModalIfVisible(page, TEST_THEME);

      // Verify branding
      await verifyChatPageBranding(page, TEST_THEME);
    });
  });

  test.afterAll(async ({ browser }) => {
    // Reset theme settings to defaults
    const context = await browser.newContext();
    const page = await context.newPage();

    try {
      await loginAs(page, "admin");
      await page.goto(`${BASE_URL}/admin/theme`);
      await page.waitForLoadState("networkidle");

      // Clear Application Display Name
      const appNameInput = page.getByRole("textbox", {
        name: /application display name/i,
      });
      await appNameInput.clear();

      // Clear Greeting Message
      const greetingInput = page.getByRole("textbox", {
        name: /greeting message/i,
      });
      await greetingInput.clear();

      // Clear Chat Header Text
      const headerInput = page.getByRole("textbox", {
        name: /chat header text/i,
      });
      await headerInput.clear();

      // Clear Chat Footer Text
      const footerTextarea = page.getByRole("textbox", {
        name: /chat footer text/i,
      });
      await footerTextarea.clear();

      // Disable Consent first (if enabled) - must be done before disabling First Visit Notice
      const consentToggle = page.getByLabel("Require Consent to Notice");
      // Check if consent toggle is visible (only visible when First Visit Notice is enabled)
      if (await consentToggle.isVisible({ timeout: 1000 }).catch(() => false)) {
        const isConsentEnabled =
          (await consentToggle.getAttribute("aria-checked")) === "true";
        if (isConsentEnabled) {
          await consentToggle.click();
          // Wait for consent prompt to disappear
          await expect(
            page.getByRole("textbox", { name: /notice consent prompt/i })
          ).not.toBeVisible({ timeout: 5000 });
        }
      }

      // Disable First Visit Notice (if enabled)
      const firstVisitToggle = page.getByLabel("Show First Visit Notice");
      const isFirstVisitEnabled =
        (await firstVisitToggle.getAttribute("aria-checked")) === "true";
      if (isFirstVisitEnabled) {
        await firstVisitToggle.click();
        // Wait for notice header to disappear
        await expect(
          page.getByRole("textbox", { name: /notice header/i })
        ).not.toBeVisible({ timeout: 5000 });
      }

      // Save changes
      const saveButton = page.getByRole("button", { name: /apply changes/i });
      const isDisabled = await saveButton.isDisabled();
      if (!isDisabled) {
        await saveButton.click();
        await expect(page.getByText(/success/i)).toBeVisible({
          timeout: 10000,
        });
      }
    } finally {
      await context.close();
    }
  });
});
