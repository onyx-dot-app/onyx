import { test, expect, Page } from "@playwright/test";
import { expectScreenshot } from "./utils/visualRegression";
import { apiLogin, loginAs, loginAsRandomUser } from "./utils/auth";
import { OnyxApiClient } from "./utils/onyxApiClient";

/**
 * Onboarding E2E tests.
 *
 * The onboarding flow appears on `/app` for users who:
 *   1. Have zero chat sessions, AND
 *   2. Have not set `hasFinishedOnboarding_{userId}` in localStorage.
 *
 * Admin users see a multi-step flow:
 *   Welcome → Name → LLM Setup → Complete (Finish Setup)
 *
 * Non-admin users see a simpler single-step name prompt.
 *
 * Every test registers a **fresh throwaway user** so the onboarding is
 * guaranteed to appear.
 *
 * NOTE: Many text elements on this page are rendered via the `Truncated`
 * component, which places a hidden offscreen copy for width measurement.
 * Because of that, `getByText(...)` can resolve to 2 elements.  We use
 * `.first()` where needed to avoid Playwright strict-mode violations.
 */

test.describe.configure({ mode: "parallel" });

const THEMES = ["light", "dark"] as const;

// ---------------------------------------------------------------------------
// Helper — create a fresh admin user and log in
// ---------------------------------------------------------------------------

async function loginAsFreshAdmin(page: Page): Promise<void> {
  // 1. Register a random (basic) user — navigates to /app
  const creds = await loginAsRandomUser(page);

  // 2. Promote to admin using the pre-provisioned admin account
  await page.context().clearCookies();
  await loginAs(page, "admin");
  const client = new OnyxApiClient(page.request);
  await client.setUserRole(creds.email, "admin");

  // 3. Log back in as the new admin
  await page.context().clearCookies();
  await apiLogin(page, creds.email, creds.password);
}

// ---------------------------------------------------------------------------
// Admin onboarding — visual regression & functional tests
// ---------------------------------------------------------------------------

for (const theme of THEMES) {
  test.describe(`Admin onboarding — ${theme}`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((t: string) => {
        localStorage.setItem("theme", t);
      }, theme);
    });

    test("Welcome step renders correctly", async ({ page }) => {
      await loginAsFreshAdmin(page);
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // The welcome header should be visible (use .first() — Truncated renders a hidden copy)
      const welcomeText = page
        .getByText("Let's take a moment to get you set up.")
        .first();
      await expect(welcomeText).toBeVisible({ timeout: 15000 });

      // "Let's Go" button should be present
      const letsGoBtn = page.getByRole("button", { name: "Let's Go" });
      await expect(letsGoBtn).toBeVisible();

      await expectScreenshot(page, {
        name: `onboarding-${theme}-welcome-step`,
        hide: ['[data-testid="onyx-logo"]'],
      });
    });

    test("Name step renders after clicking Let's Go", async ({ page }) => {
      await loginAsFreshAdmin(page);
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // Advance past welcome
      const letsGoBtn = page.getByRole("button", { name: "Let's Go" });
      await expect(letsGoBtn).toBeVisible({ timeout: 15000 });
      await letsGoBtn.click();

      // Name input should appear
      const nameInput = page.getByPlaceholder("Your name");
      await expect(nameInput).toBeVisible({ timeout: 10000 });
      await expect(
        page.getByText("What should Onyx call you?").first()
      ).toBeVisible();

      // Step indicator should show "Step 1 of 3"
      await expect(page.getByText("Step 1 of 3").first()).toBeVisible();

      await expectScreenshot(page, {
        name: `onboarding-${theme}-name-step-empty`,
        hide: ['[data-testid="onyx-logo"]'],
      });
    });

    test("Name step with filled name", async ({ page }) => {
      await loginAsFreshAdmin(page);
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      await page
        .getByRole("button", { name: "Let's Go" })
        .click({ timeout: 15000 });

      const nameInput = page.getByPlaceholder("Your name");
      await expect(nameInput).toBeVisible({ timeout: 10000 });
      await nameInput.fill("Ada Lovelace");

      // Wait for the Next button to become enabled (debounce + validation)
      const nextBtn = page.getByRole("button", { name: "Next" });
      await expect(nextBtn).toBeEnabled({ timeout: 5000 });

      await expectScreenshot(page, {
        name: `onboarding-${theme}-name-step-filled`,
        hide: ['[data-testid="onyx-logo"]'],
      });
    });

    test("LLM setup step renders", async ({ page }) => {
      await loginAsFreshAdmin(page);
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // Welcome → Name
      await page
        .getByRole("button", { name: "Let's Go" })
        .click({ timeout: 15000 });
      const nameInput = page.getByPlaceholder("Your name");
      await expect(nameInput).toBeVisible({ timeout: 10000 });
      await nameInput.fill("Ada Lovelace");

      // Wait for the Next button to become enabled (debounce + validation)
      const nextBtn = page.getByRole("button", { name: "Next" });
      await expect(nextBtn).toBeEnabled({ timeout: 5000 });

      // Name → LLM Setup
      await nextBtn.click();

      // LLM setup header (use .first() — Truncated renders a hidden copy)
      await expect(
        page.getByText("Connect your LLM models").first()
      ).toBeVisible({
        timeout: 10000,
      });

      // Step indicator should show "Step 2 of 3"
      await expect(page.getByText("Step 2 of 3").first()).toBeVisible();

      // Provider cards should be visible with "Connect" labels
      const connectLabels = page.getByText("Connect", { exact: true });
      await expect(connectLabels.first()).toBeVisible({ timeout: 10000 });

      // "View in Admin Panel" link should be present
      await expect(
        page.getByRole("link", { name: "View in Admin Panel" })
      ).toBeVisible();

      await expectScreenshot(page, {
        name: `onboarding-${theme}-llm-setup-step`,
        hide: ['[data-testid="onyx-logo"]'],
      });
    });

    test("Complete step shows final setup items", async ({ page }) => {
      await loginAsFreshAdmin(page);
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // Navigate through: Welcome → Name → LLM Setup → Complete
      await page
        .getByRole("button", { name: "Let's Go" })
        .click({ timeout: 15000 });

      const nameInput = page.getByPlaceholder("Your name");
      await expect(nameInput).toBeVisible({ timeout: 10000 });
      await nameInput.fill("Ada Lovelace");
      const nextBtn = page.getByRole("button", { name: "Next" });
      await expect(nextBtn).toBeEnabled({ timeout: 5000 });
      await nextBtn.click();

      await expect(
        page.getByText("Connect your LLM models").first()
      ).toBeVisible({
        timeout: 10000,
      });
      await page.getByRole("button", { name: "Next" }).click();

      // Complete step header (use .first() — Truncated renders a hidden copy)
      await expect(page.getByText(/You're all set/).first()).toBeVisible({
        timeout: 10000,
      });

      // Step indicator: "Step 3 of 3"
      await expect(page.getByText("Step 3 of 3").first()).toBeVisible();

      // Final step items (use .first() for Truncated text)
      await expect(
        page.getByText("Select web search provider").first()
      ).toBeVisible();
      await expect(
        page.getByText("Enable image generation").first()
      ).toBeVisible();
      await expect(page.getByText("Invite your team").first()).toBeVisible();

      // "Finish Setup" button
      const finishBtn = page.getByRole("button", { name: "Finish Setup" });
      await expect(finishBtn).toBeVisible();

      await expectScreenshot(page, {
        name: `onboarding-${theme}-complete-step`,
        hide: ['[data-testid="onyx-logo"]'],
      });
    });

    test("Finish Setup dismisses onboarding", async ({ page }) => {
      await loginAsFreshAdmin(page);
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // Walk through the full flow
      await page
        .getByRole("button", { name: "Let's Go" })
        .click({ timeout: 15000 });

      const nameInput = page.getByPlaceholder("Your name");
      await expect(nameInput).toBeVisible({ timeout: 10000 });
      await nameInput.fill("Ada Lovelace");
      const nextBtn = page.getByRole("button", { name: "Next" });
      await expect(nextBtn).toBeEnabled({ timeout: 5000 });
      await nextBtn.click();

      await expect(
        page.getByText("Connect your LLM models").first()
      ).toBeVisible({
        timeout: 10000,
      });
      await page.getByRole("button", { name: "Next" }).click();

      const finishBtn = page.getByRole("button", { name: "Finish Setup" });
      await expect(finishBtn).toBeVisible({ timeout: 10000 });
      await finishBtn.click();

      // Onboarding should disappear
      await expect(
        page.getByText("Let's take a moment to get you set up.").first()
      ).not.toBeVisible({ timeout: 5000 });

      // Chat input should now be the primary visible element
      const chatInput = page.locator("#onyx-chat-input-textarea");
      await expect(chatInput).toBeVisible({ timeout: 10000 });

      await expectScreenshot(page, {
        name: `onboarding-${theme}-post-onboarding`,
        hide: ['[data-testid="onyx-logo"]'],
      });
    });

    test("Full page screenshot at each step", async ({ page }) => {
      await loginAsFreshAdmin(page);
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // Capture the full page at the welcome step (use .first() — Truncated duplicate)
      await expect(
        page.getByText("Let's take a moment to get you set up.").first()
      ).toBeVisible({ timeout: 15000 });
      await expectScreenshot(page, {
        name: `onboarding-${theme}-full-page-welcome`,
        fullPage: true,
        hide: ['[data-testid="onyx-logo"]'],
      });

      // Advance and capture at Name step
      await page.getByRole("button", { name: "Let's Go" }).click();
      const nameInput = page.getByPlaceholder("Your name");
      await expect(nameInput).toBeVisible({ timeout: 10000 });
      await expectScreenshot(page, {
        name: `onboarding-${theme}-full-page-name`,
        fullPage: true,
        hide: ['[data-testid="onyx-logo"]'],
      });
    });
  });
}

// ---------------------------------------------------------------------------
// Non-admin onboarding
// ---------------------------------------------------------------------------

for (const theme of THEMES) {
  test.describe(`Non-admin onboarding — ${theme}`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((t: string) => {
        localStorage.setItem("theme", t);
      }, theme);
    });

    test("Non-admin sees name prompt on first visit", async ({ page }) => {
      // loginAsRandomUser creates a basic (non-admin) user
      await loginAsRandomUser(page);
      await page.waitForLoadState("networkidle");

      // Should see the name prompt
      await expect(
        page.getByText("What should Onyx call you?").first()
      ).toBeVisible({
        timeout: 15000,
      });

      const nameInput = page.getByPlaceholder("Your name");
      await expect(nameInput).toBeVisible();

      const saveBtn = page.getByRole("button", { name: "Save" });
      await expect(saveBtn).toBeVisible();
      await expect(saveBtn).toBeDisabled(); // disabled until name is entered

      await expectScreenshot(page, {
        name: `onboarding-${theme}-nonadmin-initial`,
        hide: ['[data-testid="onyx-logo"]'],
      });
    });

    test("Non-admin can save name successfully", async ({ page }) => {
      await loginAsRandomUser(page);
      await page.waitForLoadState("networkidle");

      const nameInput = page.getByPlaceholder("Your name");
      await expect(nameInput).toBeVisible({ timeout: 15000 });
      await nameInput.fill("Jane Doe");

      const saveBtn = page.getByRole("button", { name: "Save" });
      await expect(saveBtn).toBeEnabled();

      // Screenshot before saving
      await expectScreenshot(page, {
        name: `onboarding-${theme}-nonadmin-name-filled`,
        hide: ['[data-testid="onyx-logo"]'],
      });

      // Click save and wait for the personalization API call to complete.
      // After refreshUser() the parent unmounts NonAdminStep, so the
      // "You're all set!" banner may disappear almost instantly.
      const responsePromise = page.waitForResponse(
        (resp) =>
          resp.url().includes("/api/user/personalization") &&
          resp.request().method() === "PATCH" &&
          resp.status() === 200
      );
      await saveBtn.click();
      await responsePromise;

      // After save + refreshUser, the name prompt should disappear because
      // OnboardingFlow returns null when user.personalization.name is set.
      await expect(
        page.getByText("What should Onyx call you?").first()
      ).not.toBeVisible({ timeout: 10000 });

      // The chat input should now be visible (normal app state)
      const chatInput = page.locator("#onyx-chat-input-textarea");
      await expect(chatInput).toBeVisible({ timeout: 10000 });

      await expectScreenshot(page, {
        name: `onboarding-${theme}-nonadmin-saved`,
        hide: ['[data-testid="onyx-logo"]'],
      });
    });

    test("Non-admin name input accepts Enter to save", async ({ page }) => {
      await loginAsRandomUser(page);
      await page.waitForLoadState("networkidle");

      const nameInput = page.getByPlaceholder("Your name");
      await expect(nameInput).toBeVisible({ timeout: 15000 });
      await nameInput.fill("John Doe");

      // Press Enter — should trigger save
      const responsePromise = page.waitForResponse(
        (resp) =>
          resp.url().includes("/api/user/personalization") &&
          resp.request().method() === "PATCH" &&
          resp.status() === 200
      );
      await nameInput.press("Enter");
      await responsePromise;

      // Name prompt should disappear after save
      await expect(
        page.getByText("What should Onyx call you?").first()
      ).not.toBeVisible({ timeout: 10000 });
    });
  });
}

// ---------------------------------------------------------------------------
// Onboarding persistence — does not re-appear after completion
// ---------------------------------------------------------------------------

test.describe("Onboarding persistence", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("theme", "light");
    });
  });

  test("Onboarding does not reappear after Finish Setup", async ({ page }) => {
    await loginAsFreshAdmin(page);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");

    // Complete the full flow
    await page
      .getByRole("button", { name: "Let's Go" })
      .click({ timeout: 15000 });

    const nameInput = page.getByPlaceholder("Your name");
    await expect(nameInput).toBeVisible({ timeout: 10000 });
    await nameInput.fill("Ada Lovelace");
    const nextBtn = page.getByRole("button", { name: "Next" });
    await expect(nextBtn).toBeEnabled({ timeout: 5000 });
    await nextBtn.click();

    await expect(page.getByText("Connect your LLM models").first()).toBeVisible(
      {
        timeout: 10000,
      }
    );
    await page.getByRole("button", { name: "Next" }).click();

    await page
      .getByRole("button", { name: "Finish Setup" })
      .click({ timeout: 10000 });

    // Wait for onboarding to disappear
    await expect(
      page.getByText("Let's take a moment to get you set up.").first()
    ).not.toBeVisible({ timeout: 10000 });

    // Reload the page
    await page.reload();
    await page.waitForLoadState("networkidle");

    // Onboarding should NOT reappear
    await expect(
      page.getByText("Let's take a moment to get you set up.").first()
    ).not.toBeVisible({ timeout: 5000 });

    await expectScreenshot(page, {
      name: "onboarding-light-persistence-check",
      hide: ['[data-testid="onyx-logo"]'],
    });
  });
});

// ---------------------------------------------------------------------------
// Name step — keyboard interaction (admin)
// ---------------------------------------------------------------------------

test.describe("Onboarding — keyboard interaction", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("theme", "light");
    });
  });

  test("Pressing Enter in name field advances to next step", async ({
    page,
  }) => {
    await loginAsFreshAdmin(page);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");

    // Advance past welcome
    await page
      .getByRole("button", { name: "Let's Go" })
      .click({ timeout: 15000 });

    const nameInput = page.getByPlaceholder("Your name");
    await expect(nameInput).toBeVisible({ timeout: 10000 });
    await nameInput.fill("Ada Lovelace");

    // Wait for name validation to enable the action, then press Enter
    const nextBtn = page.getByRole("button", { name: "Next" });
    await expect(nextBtn).toBeEnabled({ timeout: 5000 });
    await nameInput.press("Enter");

    await expect(page.getByText("Connect your LLM models").first()).toBeVisible(
      {
        timeout: 10000,
      }
    );
  });
});
