import { test, expect } from "@tests/e2e/fixtures/eeFeatures";
import { loginAs } from "@tests/e2e/utils/auth";
import { AppearanceThemePage } from "@tests/e2e/admin/theme/AppearanceThemePage";

test.describe("Appearance Theme Settings @exclusive", () => {
  const TEST_VALUES = {
    applicationName: `TestApp${Date.now()}`,
    greetingMessage: "Welcome to our test application",
    chatHeader: "Test Header Content",
    chatFooter: "Test Footer Disclaimer",
    noticeHeader: "Important Notice",
    noticeContent: "Please read and agree to continue",
    consentPrompt: "I agree to the terms",
    customHelpLinkUrl: "https://help.example.com",
    customHelpLinkLabel: "Support Portal",
  };

  test.beforeEach(async ({ page, eeEnabled }) => {
    test.skip(
      !eeEnabled,
      "Enterprise license not active — skipping theme tests"
    );

    // Fresh session — the eeEnabled fixture already logged in to check the
    // setting, so clear cookies and re-login for a clean test state.
    await page.context().clearCookies();
    await loginAs(page, "admin");

    await page.goto("/admin/theme");
    await expect(
      page.locator('[data-label="application-name-input"]')
    ).toBeVisible({ timeout: 10_000 });

    // Clear localStorage to ensure consent modal shows
    await page.evaluate(() => {
      localStorage.removeItem("allUsersInitialPopupFlowCompleted");
    });
  });

  test.afterEach(async ({ page }) => {
    // Reset settings to defaults
    await page.goto("/admin/theme");
    await page.waitForLoadState("networkidle");

    // If the form isn't visible (e.g. EE license not active, or test failed
    // before navigating here), skip cleanup — there's nothing to reset.
    const appNameInput = page.locator('[data-label="application-name-input"]');
    if (!(await appNameInput.isVisible({ timeout: 3000 }).catch(() => false))) {
      return;
    }

    // Clear form fields
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
    const isChecked = await noticeToggle.getAttribute("aria-checked");
    if (isChecked === "true") {
      await noticeToggle.click();
      await page.waitForTimeout(300);
    }

    // Clear custom help link URL + label
    const helpLinkUrlInput = page.locator(
      '[data-label="custom-help-link-url-input"]'
    );
    if (
      await helpLinkUrlInput.isVisible({ timeout: 1000 }).catch(() => false)
    ) {
      await helpLinkUrlInput.clear();
    }
    const helpLinkLabelInput = page.locator(
      '[data-label="custom-help-link-label-input"]'
    );
    if (
      await helpLinkLabelInput.isVisible({ timeout: 1000 }).catch(() => false)
    ) {
      await helpLinkLabelInput.clear();
    }

    // Disable hide-onyx-branding toggle if enabled
    const hideBrandingToggle = page.locator(
      '[data-label="hide-onyx-branding-toggle"]'
    );
    if (
      await hideBrandingToggle.isVisible({ timeout: 1000 }).catch(() => false)
    ) {
      const hideBrandingState =
        await hideBrandingToggle.getAttribute("aria-checked");
      if (hideBrandingState === "true") {
        await hideBrandingToggle.click();
        await page.waitForTimeout(300);
      }
    }

    // Save reset. Arm the PUT waiter *before* clicking — a post-click
    // waitForResponse can miss a fast response and then hang until the test
    // timeout (the whole point of saveAndWaitForPut in AppearanceThemePage).
    // This is best-effort cleanup, so bound it and swallow a missed/absent PUT
    // rather than letting afterEach blow the 100s test budget.
    const saveButton = page.getByRole("button", { name: "Apply Changes" });
    if (await saveButton.isEnabled()) {
      const putPromise = page.waitForResponse(
        (r) =>
          r.url().includes("/api/admin/enterprise-settings") &&
          r.request().method() === "PUT",
        { timeout: 10_000 }
      );
      await saveButton.click();
      await putPromise.catch(() => {});
    }

    // Clear localStorage
    await page.evaluate(() => {
      localStorage.removeItem("allUsersInitialPopupFlowCompleted");
    });
  });

  test("admin configures branding and verifies across pages", async ({
    page,
  }) => {
    // 1. Fill in Application Name (page already navigated in beforeEach)
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
    const consentState = await consentToggle.getAttribute("aria-checked");
    if (consentState !== "true") {
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
    await page.goto("/app");
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

  test("custom help link appears in the profile popover with the configured label", async ({
    page,
  }) => {
    const themePage = new AppearanceThemePage(page);
    await themePage.fillCustomHelpLink(
      TEST_VALUES.customHelpLinkUrl,
      TEST_VALUES.customHelpLinkLabel
    );

    const response = await themePage.saveAndWaitForPut();
    expect(response.status()).toBe(200);
    await themePage.expectSaveSuccessToast();

    // Reload so the sidebar reads enterprise settings fresh — avoids any
    // SWR cache / React render race after `mutate()`.
    await themePage.reloadAndWaitForForm();

    await themePage.openUserDropdown();
    await themePage.expectCustomHelpLinkVisible(
      TEST_VALUES.customHelpLinkLabel,
      TEST_VALUES.customHelpLinkUrl
    );
  });

  test("custom help link uses the URL as the title when the label is empty", async ({
    page,
  }) => {
    const themePage = new AppearanceThemePage(page);
    await themePage.fillCustomHelpLink(TEST_VALUES.customHelpLinkUrl);

    const response = await themePage.saveAndWaitForPut();
    expect(response.status()).toBe(200);
    await themePage.expectSaveSuccessToast();

    await themePage.reloadAndWaitForForm();

    await themePage.openUserDropdown();
    // Falls back to URL itself as the displayed title
    await themePage.expectCustomHelpLinkContainsText(
      TEST_VALUES.customHelpLinkUrl,
      TEST_VALUES.customHelpLinkUrl
    );
  });

  test("validation fails when the label is set but the URL is empty", async ({
    page,
  }) => {
    const themePage = new AppearanceThemePage(page);
    await themePage.fillCustomHelpLinkLabelOnly(
      TEST_VALUES.customHelpLinkLabel
    );

    // Should NOT trigger a PUT — assert error message becomes visible
    await themePage.clickSave();
    await themePage.expectValidationMessage(
      "URL is required when a label is set"
    );

    // Clean up: clear the orphan label before afterEach runs
    await themePage.clearCustomHelpLinkLabel();
  });

  test("Hide Onyx Branding toggle removes the 'Powered by Onyx' tagline", async ({
    page,
  }) => {
    const themePage = new AppearanceThemePage(page);

    // The sidebar's "Powered by Onyx" tagline only renders alongside an
    // application name (the Logo's logo_and_name fall-through path), so
    // first set a name and save a baseline that we can then assert against.
    await themePage.setApplicationName(TEST_VALUES.applicationName);
    const baselineResponse = await themePage.saveAndWaitForPut();
    expect(baselineResponse.status()).toBe(200);
    await themePage.expectSaveSuccessToast();
    await themePage.reloadAndWaitForForm();

    // Sanity: tagline now visible alongside the application name
    await themePage.expectPoweredByOnyxVisible();

    await themePage.toggleHideBranding();

    const response = await themePage.saveAndWaitForPut();
    expect(response.status()).toBe(200);
    await themePage.expectSaveSuccessToast();

    // Reload to read the persisted setting fresh — the sidebar then re-
    // renders the Logo without the tagline.
    await themePage.reloadAndWaitForForm();
    await themePage.expectPoweredByOnyxAbsent();
  });
});
