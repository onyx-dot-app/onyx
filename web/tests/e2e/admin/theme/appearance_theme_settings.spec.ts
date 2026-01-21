import { test, expect } from "@playwright/test";
import { loginAs } from "../../utils/auth";

test.describe("Appearance Theme Settings", () => {
  const TEST_VALUES = {
    applicationName: `TestApp${Date.now()}`,
    greetingMessage: "Welcome to our test application",
    chatHeader: "Test Header Content",
    chatFooter: "Test Footer Disclaimer",
    noticeHeader: "Important Notice",
    noticeContent: "Please read and agree to continue",
    consentPrompt: "I agree to the terms",
  };

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    // Clear localStorage to ensure consent modal shows
    await page.evaluate(() => {
      localStorage.removeItem("allUsersInitialPopupFlowCompleted");
    });
  });

  test.afterEach(async ({ page }) => {
    // Reset settings to defaults
    await page.goto("http://localhost:3000/admin/theme");
    await page.waitForLoadState("networkidle");

    // Clear form fields
    const appNameInput = page.locator('[data-label="application-name-input"]');
    await appNameInput.clear();

    const greetingInput = page.locator('[data-label="greeting-message-input"]');
    await greetingInput.clear();

    const headerInput = page.locator('[data-label="chat-header-input"]');
    await headerInput.clear();

    const footerTextarea = page.locator('[data-label="chat-footer-textarea"]');
    await footerTextarea.clear();

    // Disable notice toggle if enabled
    const noticeToggle = page.locator(
      '[data-label="first-visit-notice-toggle"]'
    );
    const isChecked = await noticeToggle.getAttribute("data-state");
    if (isChecked === "checked") {
      await noticeToggle.click();
      await page.waitForTimeout(300);
    }

    // Save reset
    const saveButton = page.getByRole("button", { name: "Apply Changes" });
    if (await saveButton.isEnabled()) {
      await saveButton.click();
      await page.waitForResponse(
        (r) =>
          r.url().includes("/api/admin/enterprise-settings") &&
          r.request().method() === "PUT"
      );
    }

    // Clear localStorage
    await page.evaluate(() => {
      localStorage.removeItem("allUsersInitialPopupFlowCompleted");
    });
  });

  test("admin configures branding and verifies across pages", async ({
    page,
  }) => {
    // 1. Navigate to theme page
    await page.goto("http://localhost:3000/admin/theme");
    await page.waitForLoadState("networkidle");

    // 2. Fill in Application Name
    const appNameInput = page.locator('[data-label="application-name-input"]');
    await appNameInput.fill(TEST_VALUES.applicationName);

    // 3. Fill in Greeting Message
    const greetingInput = page.locator('[data-label="greeting-message-input"]');
    await greetingInput.fill(TEST_VALUES.greetingMessage);

    // 4. Fill in Chat Header
    const headerInput = page.locator('[data-label="chat-header-input"]');
    await headerInput.fill(TEST_VALUES.chatHeader);

    // 5. Fill in Chat Footer
    const footerTextarea = page.locator('[data-label="chat-footer-textarea"]');
    await footerTextarea.fill(TEST_VALUES.chatFooter);

    // 6. Enable First Visit Notice
    const noticeToggle = page.locator(
      '[data-label="first-visit-notice-toggle"]'
    );
    await noticeToggle.click();

    // 7. Fill Notice Header (wait for it to be visible first)
    const noticeHeaderInput = page.locator(
      '[data-label="notice-header-input"]'
    );
    await expect(noticeHeaderInput).toBeVisible({ timeout: 5000 });
    await noticeHeaderInput.fill(TEST_VALUES.noticeHeader);

    // 8. Fill Notice Content
    const noticeContentTextarea = page.locator(
      '[data-label="notice-content-textarea"]'
    );
    await noticeContentTextarea.fill(TEST_VALUES.noticeContent);

    // 9. Enable Consent Requirement (only if not already enabled)
    const consentToggle = page.locator('[data-label="require-consent-toggle"]');
    const consentState = await consentToggle.getAttribute("data-state");
    if (consentState !== "checked") {
      await consentToggle.click();
    }

    // 10. Fill Consent Prompt (wait for it to be visible first)
    const consentPromptTextarea = page.locator(
      '[data-label="consent-prompt-textarea"]'
    );
    await expect(consentPromptTextarea).toBeVisible({ timeout: 5000 });
    await consentPromptTextarea.fill(TEST_VALUES.consentPrompt);

    // 11. Click Apply Changes
    const saveButton = page.getByRole("button", { name: "Apply Changes" });
    await expect(saveButton).toBeEnabled();
    await saveButton.click();

    // 12. Wait for API response
    const response = await page.waitForResponse(
      (r) =>
        r.url().includes("/api/admin/enterprise-settings") &&
        r.request().method() === "PUT",
      { timeout: 10000 }
    );
    expect(response.status()).toBe(200);

    // 13. Wait for success message
    await expect(page.getByText(/successfully/i)).toBeVisible({
      timeout: 5000,
    });

    // 14. Verify admin sidebar has branding (application name)
    await expect(
      page.getByText(TEST_VALUES.applicationName).first()
    ).toBeVisible({
      timeout: 5000,
    });

    // 15. Navigate to chat page
    // Clear localStorage again right before navigation to ensure consent modal shows
    await page.evaluate(() => {
      localStorage.removeItem("allUsersInitialPopupFlowCompleted");
    });
    await page.goto("http://localhost:3000/chat");
    await page.waitForLoadState("networkidle");

    // 16. Handle consent modal
    const modal = page.getByRole("dialog");
    await expect(modal).toBeVisible({ timeout: 15000 });

    // Verify notice header and content
    await expect(
      modal.getByText(TEST_VALUES.noticeHeader).first()
    ).toBeVisible();
    await expect(
      modal.getByText(TEST_VALUES.noticeContent).first()
    ).toBeVisible();

    // Check consent checkbox
    const checkbox = modal.getByLabel("Consent checkbox");
    await checkbox.click();

    // Click Start button
    const startButton = modal.getByRole("button", { name: "Start" });
    await startButton.click();

    // Wait for modal to close
    await expect(modal).not.toBeVisible({ timeout: 5000 });

    // 17. Verify sidebar branding on chat page
    await expect(
      page.getByText(TEST_VALUES.applicationName).first()
    ).toBeVisible();

    // 18. Verify greeting message on welcome screen
    await expect(page.getByText(TEST_VALUES.greetingMessage)).toBeVisible();

    // 19. Verify chat header content
    await expect(page.getByText(TEST_VALUES.chatHeader)).toBeVisible();

    // 20. Verify chat footer content
    await expect(page.getByText(TEST_VALUES.chatFooter)).toBeVisible();
  });
});
