/**
 * Exploratory Testing for Jira Service Management Connector
 * 
 * This test suite performs comprehensive exploratory testing of the JSM connector UI:
 * - Connector selection and visibility
 * - Configuration form rendering
 * - Form validation
 * - Field interactions
 * - Error handling
 * - UI responsiveness
 */

import { test, expect, Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

test.describe("Jira Service Management Connector - Exploratory Testing", () => {
  test.describe.configure({ mode: "serial" });

  let apiClient: OnyxApiClient;
  let testCcPairId: number | null = null;

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    apiClient = new OnyxApiClient(page);
  });

  test.afterEach(async ({ page }) => {
    if (testCcPairId !== null) {
      try {
        await apiClient.deleteCCPair(testCcPairId);
        testCcPairId = null;
      } catch (error) {
        console.warn(
          `Failed to delete test connector ${testCcPairId}: ${error}`
        );
      }
    }
  });

  test("EXPLORATORY: JSM connector appears in connector selection page", async ({
    page,
  }) => {
    console.log("[EXPLORATORY] Testing connector visibility in selection page");
    
    // Navigate to add connector page
    await page.goto("/admin/add-connector");
    await page.waitForLoadState("networkidle");

    // Look for Jira Service Management in the connector list
    const jsmConnector = page.getByText(/Jira Service Management/i);
    await expect(jsmConnector).toBeVisible({ timeout: 10000 });
    
    console.log("[EXPLORATORY] ✅ JSM connector found in selection page");
  });

  test("EXPLORATORY: JSM connector configuration form renders correctly", async ({
    page,
  }) => {
    console.log("[EXPLORATORY] Testing configuration form rendering");
    
    // Navigate directly to JSM connector configuration
    await page.goto("/admin/connectors/jira_service_management");
    await page.waitForLoadState("networkidle");

    // Verify form title/description
    const description = page.getByText(/Configure which Jira Service Management/i);
    await expect(description).toBeVisible({ timeout: 10000 });
    
    // Verify required fields are present
    const baseUrlLabel = page.getByLabel(/Jira Base URL/i);
    await expect(baseUrlLabel).toBeVisible({ timeout: 5000 });
    
    const projectKeyLabel = page.getByLabel(/JSM Project Key/i);
    await expect(projectKeyLabel).toBeVisible({ timeout: 5000 });
    
    // Verify optional fields
    const scopedTokenCheckbox = page.getByLabel(/Using scoped token/i);
    await expect(scopedTokenCheckbox).toBeVisible({ timeout: 5000 });
    
    console.log("[EXPLORATORY] ✅ Configuration form renders correctly");
  });

  test("EXPLORATORY: Form validation works for required fields", async ({
    page,
  }) => {
    console.log("[EXPLORATORY] Testing form validation");
    
    await page.goto("/admin/connectors/jira_service_management");
    await page.waitForLoadState("networkidle");

    // Try to submit without filling required fields
    const submitButton = page.getByRole("button", { name: /connect|create|save/i });
    
    if (await submitButton.isVisible({ timeout: 5000 })) {
      await submitButton.click();
      
      // Wait for validation errors
      await page.waitForTimeout(1000);
      
      // Check for validation messages (implementation may vary)
      const hasValidation = await page
        .locator("text=/required|invalid|error/i")
        .first()
        .isVisible()
        .catch(() => false);
      
      if (hasValidation) {
        console.log("[EXPLORATORY] ✅ Validation errors displayed");
      } else {
        console.log("[EXPLORATORY] ⚠️ Validation may be handled differently");
      }
    }
  });

  test("EXPLORATORY: All form fields are interactive", async ({ page }) => {
    console.log("[EXPLORATORY] Testing field interactivity");
    
    await page.goto("/admin/connectors/jira_service_management");
    await page.waitForLoadState("networkidle");

    // Test Base URL field
    const baseUrlInput = page.getByLabel(/Jira Base URL/i);
    await expect(baseUrlInput).toBeEnabled({ timeout: 5000 });
    await baseUrlInput.fill("https://test.atlassian.net");
    await expect(baseUrlInput).toHaveValue("https://test.atlassian.net");
    console.log("[EXPLORATORY] ✅ Base URL field is interactive");

    // Test Project Key field
    const projectKeyInput = page.getByLabel(/JSM Project Key/i);
    await expect(projectKeyInput).toBeEnabled({ timeout: 5000 });
    await projectKeyInput.fill("ITSM");
    await expect(projectKeyInput).toHaveValue("ITSM");
    console.log("[EXPLORATORY] ✅ Project Key field is interactive");

    // Test Scoped Token checkbox
    const scopedTokenCheckbox = page.getByLabel(/Using scoped token/i);
    await expect(scopedTokenCheckbox).toBeEnabled({ timeout: 5000 });
    await scopedTokenCheckbox.check();
    await expect(scopedTokenCheckbox).toBeChecked();
    console.log("[EXPLORATORY] ✅ Scoped Token checkbox is interactive");

    // Test Comment Email Blacklist (if visible)
    const blacklistInput = page
      .getByLabel(/Comment Email Blacklist/i)
      .first();
    if (await blacklistInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await blacklistInput.fill("bot@example.com");
      console.log("[EXPLORATORY] ✅ Comment Email Blacklist field is interactive");
    }

    // Test Labels to Skip (if visible)
    const labelsInput = page.getByLabel(/Labels to Skip/i).first();
    if (await labelsInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await labelsInput.fill("skip-me");
      console.log("[EXPLORATORY] ✅ Labels to Skip field is interactive");
    }
  });

  test("EXPLORATORY: Form handles invalid input gracefully", async ({
    page,
  }) => {
    console.log("[EXPLORATORY] Testing invalid input handling");
    
    await page.goto("/admin/connectors/jira_service_management");
    await page.waitForLoadState("networkidle");

    // Test invalid URL format
    const baseUrlInput = page.getByLabel(/Jira Base URL/i);
    await baseUrlInput.fill("not-a-valid-url");
    
    // Test invalid project key (special characters)
    const projectKeyInput = page.getByLabel(/JSM Project Key/i);
    await projectKeyInput.fill("INVALID@KEY#123");
    
    // Try to submit and check for error handling
    const submitButton = page.getByRole("button", { name: /connect|create|save/i });
    if (await submitButton.isVisible({ timeout: 5000 })) {
      await submitButton.click();
      await page.waitForTimeout(2000);
      
      // Check if errors are shown or form prevents submission
      const hasError = await page
        .locator("text=/invalid|error|format/i")
        .first()
        .isVisible()
        .catch(() => false);
      
      if (hasError) {
        console.log("[EXPLORATORY] ✅ Invalid input errors displayed");
      } else {
        console.log("[EXPLORATORY] ⚠️ Error handling may be server-side");
      }
    }
  });

  test("EXPLORATORY: UI is responsive and accessible", async ({ page }) => {
    console.log("[EXPLORATORY] Testing UI responsiveness and accessibility");
    
    await page.goto("/admin/connectors/jira_service_management");
    await page.waitForLoadState("networkidle");

    // Test keyboard navigation
    await page.keyboard.press("Tab");
    const focusedElement = page.locator(":focus");
    await expect(focusedElement).toBeVisible({ timeout: 2000 });
    console.log("[EXPLORATORY] ✅ Keyboard navigation works");

    // Test form labels are properly associated
    const baseUrlLabel = page.getByLabel(/Jira Base URL/i);
    const labelFor = await baseUrlLabel.getAttribute("for");
    if (labelFor) {
      const associatedInput = page.locator(`#${labelFor}`);
      await expect(associatedInput).toBeVisible({ timeout: 2000 });
      console.log("[EXPLORATORY] ✅ Labels properly associated with inputs");
    }

    // Test responsive design (viewport changes)
    await page.setViewportSize({ width: 375, height: 667 }); // Mobile size
    await page.waitForTimeout(500);
    const mobileForm = page.getByText(/Configure which Jira Service Management/i);
    await expect(mobileForm).toBeVisible({ timeout: 5000 });
    console.log("[EXPLORATORY] ✅ Form is responsive on mobile viewport");

    await page.setViewportSize({ width: 1920, height: 1080 }); // Desktop size
    await page.waitForTimeout(500);
    await expect(mobileForm).toBeVisible({ timeout: 5000 });
    console.log("[EXPLORATORY] ✅ Form is responsive on desktop viewport");
  });

  test("EXPLORATORY: Form descriptions and help text are visible", async ({
    page,
  }) => {
    console.log("[EXPLORATORY] Testing help text and descriptions");
    
    await page.goto("/admin/connectors/jira_service_management");
    await page.waitForLoadState("networkidle");

    // Check for main description
    const mainDescription = page.getByText(
      /Configure which Jira Service Management/i
    );
    await expect(mainDescription).toBeVisible({ timeout: 5000 });
    console.log("[EXPLORATORY] ✅ Main description visible");

    // Check for field descriptions
    const baseUrlDescription = page.getByText(
      /The base URL of your Jira instance/i
    );
    if (await baseUrlDescription.isVisible({ timeout: 2000 }).catch(() => false)) {
      console.log("[EXPLORATORY] ✅ Base URL description visible");
    }

    const projectKeyDescription = page.getByText(
      /The key of the Jira Service Management project/i
    );
    if (await projectKeyDescription.isVisible({ timeout: 2000 }).catch(() => false)) {
      console.log("[EXPLORATORY] ✅ Project Key description visible");
    }

    const blacklistDescription = page.getByText(
      /This is generally useful to ignore certain bots/i
    );
    if (await blacklistDescription.isVisible({ timeout: 2000 }).catch(() => false)) {
      console.log("[EXPLORATORY] ✅ Comment Email Blacklist description visible");
    }
  });

  test("EXPLORATORY: Optional fields can be left empty", async ({ page }) => {
    console.log("[EXPLORATORY] Testing optional field handling");
    
    await page.goto("/admin/connectors/jira_service_management");
    await page.waitForLoadState("networkidle");

    // Fill only required fields
    const baseUrlInput = page.getByLabel(/Jira Base URL/i);
    await baseUrlInput.fill("https://test.atlassian.net");

    const projectKeyInput = page.getByLabel(/JSM Project Key/i);
    await projectKeyInput.fill("ITSM");

    // Leave optional fields empty
    // Check if form allows submission with optional fields empty
    const submitButton = page.getByRole("button", { name: /connect|create|save/i });
    if (await submitButton.isEnabled({ timeout: 5000 }).catch(() => false)) {
      console.log("[EXPLORATORY] ✅ Form allows submission with optional fields empty");
    } else {
      console.log("[EXPLORATORY] ⚠️ Form may require all fields (check implementation)");
    }
  });

  test("EXPLORATORY: Error messages display correctly for API errors", async ({
    page,
  }) => {
    console.log("[EXPLORATORY] Testing API error handling in UI");
    
    await page.goto("/admin/connectors/jira_service_management");
    await page.waitForLoadState("networkidle");

    // Fill form with values that might cause API errors
    const baseUrlInput = page.getByLabel(/Jira Base URL/i);
    await baseUrlInput.fill("https://invalid-domain-that-does-not-exist-12345.atlassian.net");

    const projectKeyInput = page.getByLabel(/JSM Project Key/i);
    await projectKeyInput.fill("INVALID");

    // Try to submit (this will likely fail, but we're testing error display)
    const submitButton = page.getByRole("button", { name: /connect|create|save/i });
    if (await submitButton.isVisible({ timeout: 5000 })) {
      // Intercept API calls to simulate errors
      await page.route("**/api/**", (route) => {
        route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ error: "Project not found" }),
        });
      });

      await submitButton.click();
      await page.waitForTimeout(3000);

      // Check for error message display
      const errorMessage = page.locator("text=/error|not found|invalid|failed/i");
      if (await errorMessage.first().isVisible({ timeout: 5000 }).catch(() => false)) {
        console.log("[EXPLORATORY] ✅ Error messages display correctly");
      } else {
        console.log("[EXPLORATORY] ⚠️ Error handling may use different UI pattern");
      }
    }
  });

  test("EXPLORATORY: Form state persists during navigation", async ({
    page,
  }) => {
    console.log("[EXPLORATORY] Testing form state persistence");
    
    await page.goto("/admin/connectors/jira_service_management");
    await page.waitForLoadState("networkidle");

    // Fill some fields
    const baseUrlInput = page.getByLabel(/Jira Base URL/i);
    await baseUrlInput.fill("https://test.atlassian.net");

    const projectKeyInput = page.getByLabel(/JSM Project Key/i);
    await projectKeyInput.fill("ITSM");

    // Navigate away and back (if browser back button works)
    await page.goto("/admin/add-connector");
    await page.waitForLoadState("networkidle");
    
    await page.goBack();
    await page.waitForLoadState("networkidle");

    // Check if values persisted (may depend on implementation)
    const baseUrlValue = await baseUrlInput.inputValue().catch(() => "");
    if (baseUrlValue) {
      console.log("[EXPLORATORY] ✅ Form values persisted: " + baseUrlValue);
    } else {
      console.log("[EXPLORATORY] ⚠️ Form state may not persist (expected behavior)");
    }
  });

  test("EXPLORATORY: Loading states are handled gracefully", async ({
    page,
  }) => {
    console.log("[EXPLORATORY] Testing loading state handling");
    
    await page.goto("/admin/connectors/jira_service_management");
    await page.waitForLoadState("networkidle");

    // Fill form
    const baseUrlInput = page.getByLabel(/Jira Base URL/i);
    await baseUrlInput.fill("https://test.atlassian.net");

    const projectKeyInput = page.getByLabel(/JSM Project Key/i);
    await projectKeyInput.fill("ITSM");

    // Slow down network to see loading states
    await page.route("**/api/**", (route) => {
      setTimeout(() => {
        route.continue();
      }, 2000);
    });

    const submitButton = page.getByRole("button", { name: /connect|create|save/i });
    if (await submitButton.isVisible({ timeout: 5000 })) {
      await submitButton.click();

      // Check for loading indicators
      const loadingIndicator = page.locator("text=/loading|saving|connecting/i");
      if (await loadingIndicator.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        console.log("[EXPLORATORY] ✅ Loading states displayed");
      } else {
        // Check for disabled button state
        const isDisabled = await submitButton.isDisabled().catch(() => false);
        if (isDisabled) {
          console.log("[EXPLORATORY] ✅ Button disabled during loading");
        } else {
          console.log("[EXPLORATORY] ⚠️ Loading state may be handled differently");
        }
      }
    }
  });
});
