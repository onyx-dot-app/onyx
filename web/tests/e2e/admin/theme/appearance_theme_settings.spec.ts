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
  });
});
