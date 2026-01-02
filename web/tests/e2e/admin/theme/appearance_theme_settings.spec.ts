import { test, expect } from "@playwright/test";
import { loginAs, loginAsRandomUser } from "../../utils/auth";

const TEST_THEME = {
  applicationName: "Acme Corp Chat",
  greetingMessage: "Welcome to Acme Corp",
  chatHeaderText: "Acme Internal Assistant",
  chatFooterText: "Powered by Acme Corp AI",
  noticeHeader: "Important Notice",
  noticeContent: "Please review our usage policy before continuing.",
  consentPrompt: "I agree to the terms and conditions",
};

async function handleFirstVisitNotice(
  page: import("@playwright/test").Page,
  expected: typeof TEST_THEME
) {
  // Wait for modal to appear
  const modal = page.getByRole("dialog");
  await expect(modal).toBeVisible({ timeout: 10000 });

  // Verify notice header
  await expect(modal.getByText(expected.noticeHeader)).toBeVisible();

  // Verify notice content
  await expect(modal.getByText(expected.noticeContent)).toBeVisible();

  // Verify consent prompt is visible
  await expect(modal.getByText(expected.consentPrompt)).toBeVisible();

  // Check the consent checkbox
  const checkbox = modal.getByRole("checkbox");
  await checkbox.check();

  // Click Start button to dismiss
  const startButton = modal.getByRole("button", { name: /start/i });
  await startButton.click();

  // Verify modal is dismissed
  await expect(modal).not.toBeVisible({ timeout: 5000 });
}

async function verifyChatPageBranding(
  page: import("@playwright/test").Page,
  expected: typeof TEST_THEME
) {
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
      await page.goto("http://localhost:3000/admin/theme");
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

      // Enable First Visit Notice
      const firstVisitToggle = page
        .locator("label", { hasText: /show first visit notice/i })
        .locator("..")
        .getByRole("switch");
      await firstVisitToggle.click();
      await page.waitForTimeout(300);

      // Fill Notice Header (appears after toggle)
      const noticeHeaderInput = page.getByRole("textbox", {
        name: /notice header/i,
      });
      await noticeHeaderInput.fill(TEST_THEME.noticeHeader);

      // Fill Notice Content
      const noticeContentTextarea = page
        .getByPlaceholder("Add markdown content")
        .first();
      await noticeContentTextarea.fill(TEST_THEME.noticeContent);

      // Enable Require Consent
      const consentToggle = page
        .locator("label", { hasText: /require consent to notice/i })
        .locator("..")
        .getByRole("switch");
      await consentToggle.click();
      await page.waitForTimeout(300);

      // Fill Consent Prompt (appears after toggle)
      const consentPromptTextarea = page
        .getByPlaceholder("Add markdown content")
        .last();
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
      await page.goto("http://localhost:3000");
      await page.evaluate(() => {
        localStorage.removeItem("allUsersInitialPopupFlowCompleted");
      });

      await loginAs(page, "admin");

      // Navigate to chat page
      await page.goto("http://localhost:3000/chat");
      await page.waitForLoadState("networkidle");

      // Handle and verify first visit notice
      await handleFirstVisitNotice(page, TEST_THEME);
    });

    test("Admin sees correct branding on chat page", async ({ page }) => {
      // Login as admin (localStorage should persist from previous test)
      await page.context().clearCookies();
      await loginAs(page, "admin");

      // Navigate to chat page
      await page.goto("http://localhost:3000/chat");
      await page.waitForLoadState("networkidle");

      // The first visit notice should not appear since we completed it in the previous test
      // But if it does appear (fresh session), handle it
      const modal = page.getByRole("dialog");
      if (await modal.isVisible({ timeout: 2000 }).catch(() => false)) {
        await handleFirstVisitNotice(page, TEST_THEME);
      }

      // Verify branding
      await verifyChatPageBranding(page, TEST_THEME);
    });

    test("Admin sees correct branding on admin sidebar", async ({ page }) => {
      // Login as admin
      await page.context().clearCookies();
      await loginAs(page, "admin");

      // Navigate to admin theme page (or any admin page)
      await page.goto("http://localhost:3000/admin/theme");
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
      const modal = page.getByRole("dialog");
      if (await modal.isVisible({ timeout: 2000 }).catch(() => false)) {
        await handleFirstVisitNotice(page, TEST_THEME);
      }

      // Navigate to chat page (in case signup redirected elsewhere)
      await page.goto("http://localhost:3000/chat");
      await page.waitForLoadState("networkidle");

      // Handle first visit notice again if it appears
      if (await modal.isVisible({ timeout: 2000 }).catch(() => false)) {
        await handleFirstVisitNotice(page, TEST_THEME);
      }

      // Verify branding
      await verifyChatPageBranding(page, TEST_THEME);
    });
  });
});
