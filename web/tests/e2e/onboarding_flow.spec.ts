import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs, loginAsRandomUser, apiLogin } from "./utils/auth";
import { OnyxApiClient } from "./utils/onyxApiClient";
import {
  expectScreenshot,
  expectElementScreenshot,
} from "./utils/visualRegression";

/**
 * Onboarding E2E Tests
 *
 * Covers the four main user scenarios:
 *   1. Admin  WITHOUT LLM providers → Full 4-step onboarding, chat disabled
 *   2. Admin  WITH    LLM providers → No full onboarding, simple name prompt
 *   3. Non-admin WITHOUT LLM providers → Name prompt only, chat disabled
 *   4. Non-admin WITH    LLM providers → Name prompt only, chat enabled
 *
 * The admin onboarding flow (Welcome → Name → LLM Setup → Complete) appears
 * on `/app` for admin users who:
 *   1. Have zero chat sessions, AND
 *   2. Have no LLM providers configured (`hasAnyProvider === false`).
 *
 * Both conditions are enforced by `useShowOnboarding` in
 * `web/src/hooks/useShowOnboarding.ts`.  There is no localStorage key
 * involved — the check is purely server-state-driven.
 *
 * Non-admin users see a simpler single-step name prompt whenever
 * `user.personalization.name` is not set, regardless of LLM providers.
 *
 * Marked @exclusive because scenarios 1 & 3 delete all LLM providers,
 * which is shared backend state.  The exclusive Playwright project runs
 * tests serially in a single worker to prevent provider-mutation races.
 *
 * NOTE: Many text elements on the onboarding page are rendered via the
 * `Truncated` component, which places a hidden offscreen copy for width
 * measurement.  `getByText(...)` can therefore resolve to 2 elements —
 * we use `.first()` where needed to avoid strict-mode violations.
 */

const THEMES = ["light", "dark"] as const;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function deleteAllProviders(client: OnyxApiClient): Promise<void> {
  const providers = await client.listLlmProviders();
  for (const provider of providers) {
    try {
      await client.deleteProvider(provider.id);
    } catch (error) {
      console.warn(
        `Failed to delete provider ${provider.id}: ${String(error)}`
      );
    }
  }
}

async function createFreshAdmin(
  page: Page
): Promise<{ email: string; password: string }> {
  await page.context().clearCookies();
  const { email, password } = await loginAsRandomUser(page);

  // Promote the new user to admin via the pre-provisioned admin
  await page.context().clearCookies();
  await loginAs(page, "admin");
  const adminClient = new OnyxApiClient(page.request);
  await adminClient.setUserRole(email, "admin");

  // Log back in as the new admin
  await page.context().clearCookies();
  await apiLogin(page, email, password);

  return { email, password };
}

async function createFreshUser(
  page: Page
): Promise<{ email: string; password: string }> {
  await page.context().clearCookies();
  return await loginAsRandomUser(page);
}

/**
 * Connect an LLM provider through the onboarding form UI.
 *
 * The "Next" button on the LLM step is disabled until a provider is connected
 * via the form (which calls `setButtonActive(true)` internally).  We cannot
 * simply create a provider via the API because `useLLMProviders` has
 * `dedupingInterval: 60 000` — SWR will not re-fetch for a full minute, so
 * the button stays disabled.
 *
 * To avoid depending on an external LLM service being reachable, the
 * `/api/admin/llm/test` endpoint is intercepted and returns 200 immediately.
 */
async function connectProviderViaForm(page: Page): Promise<void> {
  // Mock the LLM key-test endpoint so the form succeeds without hitting OpenAI
  await page.route("**/api/admin/llm/test", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "{}",
    })
  );

  // Wait for provider cards to finish loading
  await expect(page.getByText("Connect", { exact: true }).first()).toBeVisible({
    timeout: 10000,
  });

  // Click the first provider card (GPT / OpenAI) to open its connection form
  await page
    .locator('[role="button"]')
    .filter({ hasText: "GPT" })
    .first()
    .click();

  // Fill the API key — the test endpoint is mocked so any value works
  const dialog = page.locator('[role="dialog"]');
  await expect(dialog).toBeVisible({ timeout: 5000 });
  await dialog.locator("input").first().fill("e2e-test-api-key");

  // Click the modal's "Connect" submit button
  await dialog.getByRole("button", { name: "Connect" }).click();

  // Wait for the modal to close (provider created, button enabled)
  await expect(dialog).not.toBeVisible({ timeout: 15000 });

  // Clean up the route mock
  await page.unroute("**/api/admin/llm/test");
}

/**
 * Navigate from Welcome through to the Complete step:
 *   Welcome → Name (fill "Ada Lovelace") → LLM Setup → connect provider → Complete
 *
 * Uses {@link connectProviderViaForm} to advance past the LLM step.
 */
async function navigateToCompleteStep(page: Page): Promise<void> {
  // Welcome → Let's Go
  await page
    .getByRole("button", { name: "Let's Go" })
    .click({ timeout: 15000 });

  // Name step — fill and advance
  const nameInput = page.getByPlaceholder("Your name");
  await expect(nameInput).toBeVisible({ timeout: 10000 });
  await nameInput.fill("Ada Lovelace");
  const nextBtn = page.getByRole("button", { name: "Next" });
  await expect(nextBtn).toBeEnabled({ timeout: 5000 });
  await nextBtn.click();

  // Wait for LLM step to render
  await expect(page.getByText("Connect your LLM models").first()).toBeVisible({
    timeout: 10000,
  });

  // Connect a provider through the onboarding form
  await connectProviderViaForm(page);

  // The form called setButtonActive(true), so Next is enabled
  await expect(nextBtn).toBeEnabled({ timeout: 5000 });
  await nextBtn.click();

  // Wait for Complete step
  await expect(page.getByText(/You're all set/).first()).toBeVisible({
    timeout: 15000,
  });
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test.describe("Onboarding E2E @exclusive", () => {
  // ─── Scenario 1: Admin WITHOUT LLM providers ────────────────────────
  test.describe("Admin without LLM providers", () => {
    test.beforeEach(async ({ page }) => {
      // Delete all providers (as existing admin)
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await deleteAllProviders(adminClient);

      // Create a fresh admin user (no chat history, no name)
      await createFreshAdmin(page);
    });

    test.afterEach(async ({ page }) => {
      // Restore at least one public provider for other test suites
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await adminClient.ensurePublicProvider();
    });

    // ── Functional tests ────────────────────────────────────────────

    test("shows full onboarding flow with Welcome step", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const onboardingFlow = page.locator('[aria-label="onboarding-flow"]');
      await expect(onboardingFlow).toBeVisible({ timeout: 15000 });

      const header = page.locator('[data-label="onboarding-header"]');
      await expect(header).toBeVisible();
      await expect(
        header.getByRole("button", { name: "Let's Go" })
      ).toBeVisible();

      await expectElementScreenshot(header, {
        name: "onboarding-welcome-step",
      });
    });

    test("chat input bar is disabled during onboarding", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      await expect(page.locator('[aria-label="onboarding-flow"]')).toBeVisible({
        timeout: 15000,
      });

      const chatInput = page.locator("#onyx-chat-input");
      await expect(chatInput).toHaveAttribute("aria-disabled", "true");

      await expectElementScreenshot(chatInput, {
        name: "onboarding-chat-disabled",
      });
    });

    test("can progress through onboarding steps", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const header = page.locator('[data-label="onboarding-header"]');
      await expect(header).toBeVisible({ timeout: 15000 });
      await header.getByRole("button", { name: "Let's Go" }).click();

      const nameStep = page.locator('[aria-label="onboarding-name-step"]');
      await expect(nameStep).toBeVisible({ timeout: 10000 });
      await nameStep.getByPlaceholder("Your name").fill("Test Admin");

      await expectElementScreenshot(nameStep, {
        name: "onboarding-name-step",
      });

      const nextButton = header.getByRole("button", { name: "Next" });
      await expect(nextButton).toBeEnabled({ timeout: 10000 });
      await nextButton.click();

      const llmStep = page.locator('[aria-label="onboarding-llm-step"]');
      await expect(llmStep).toBeVisible({ timeout: 10000 });

      await expectElementScreenshot(llmStep, {
        name: "onboarding-llm-step",
      });
    });

    test("can complete full onboarding via provider form", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      await navigateToCompleteStep(page);

      await expect(page.getByText("Step 3 of 3").first()).toBeVisible();

      const finishBtn = page.getByRole("button", { name: "Finish Setup" });
      await expect(finishBtn).toBeVisible();
      await finishBtn.click();

      await expect(
        page.getByText("Let's take a moment to get you set up.").first()
      ).not.toBeVisible({ timeout: 5000 });

      const chatInput = page.locator("#onyx-chat-input-textarea");
      await expect(chatInput).toBeVisible({ timeout: 10000 });
    });

    test("Enter in name field advances to LLM step", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      await page
        .getByRole("button", { name: "Let's Go" })
        .click({ timeout: 15000 });

      const nameInput = page.getByPlaceholder("Your name");
      await expect(nameInput).toBeVisible({ timeout: 10000 });
      await nameInput.fill("Ada Lovelace");

      const nextBtn = page.getByRole("button", { name: "Next" });
      await expect(nextBtn).toBeEnabled({ timeout: 5000 });
      await nameInput.press("Enter");

      await expect(
        page.getByText("Connect your LLM models").first()
      ).toBeVisible({ timeout: 10000 });
    });

    test("onboarding does not reappear after Finish Setup", async ({
      page,
    }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      await navigateToCompleteStep(page);

      await page
        .getByRole("button", { name: "Finish Setup" })
        .click({ timeout: 10000 });

      await expect(
        page.getByText("Let's take a moment to get you set up.").first()
      ).not.toBeVisible({ timeout: 10000 });

      // Reload and verify onboarding stays dismissed
      await page.reload();
      await page.waitForLoadState("networkidle");

      await expect(
        page.getByText("Let's take a moment to get you set up.").first()
      ).not.toBeVisible({ timeout: 5000 });

      await expectScreenshot(page, {
        name: "onboarding-light-persistence-check",
        hide: ['[data-testid="onyx-logo"]'],
      });
    });

    // ── Theme-variant visual regression tests ───────────────────────

    for (const theme of THEMES) {
      test.describe(`Visual regression — ${theme}`, () => {
        test("Welcome step", async ({ page }) => {
          await page.addInitScript(
            (t: string) => localStorage.setItem("theme", t),
            theme
          );
          await page.goto("/app");
          await page.waitForLoadState("networkidle");

          const welcomeText = page
            .getByText("Let's take a moment to get you set up.")
            .first();
          await expect(welcomeText).toBeVisible({ timeout: 15000 });
          await expect(
            page.getByRole("button", { name: "Let's Go" })
          ).toBeVisible();

          await expectScreenshot(page, {
            name: `onboarding-${theme}-welcome-step`,
            hide: ['[data-testid="onyx-logo"]'],
          });
        });

        test("Name step empty", async ({ page }) => {
          await page.addInitScript(
            (t: string) => localStorage.setItem("theme", t),
            theme
          );
          await page.goto("/app");
          await page.waitForLoadState("networkidle");

          await page
            .getByRole("button", { name: "Let's Go" })
            .click({ timeout: 15000 });

          const nameInput = page.getByPlaceholder("Your name");
          await expect(nameInput).toBeVisible({ timeout: 10000 });
          await expect(
            page.getByText("What should Onyx call you?").first()
          ).toBeVisible();
          await expect(page.getByText("Step 1 of 3").first()).toBeVisible();

          await expectScreenshot(page, {
            name: `onboarding-${theme}-name-step-empty`,
            hide: ['[data-testid="onyx-logo"]'],
          });
        });

        test("Name step filled", async ({ page }) => {
          await page.addInitScript(
            (t: string) => localStorage.setItem("theme", t),
            theme
          );
          await page.goto("/app");
          await page.waitForLoadState("networkidle");

          await page
            .getByRole("button", { name: "Let's Go" })
            .click({ timeout: 15000 });

          const nameInput = page.getByPlaceholder("Your name");
          await expect(nameInput).toBeVisible({ timeout: 10000 });
          await nameInput.fill("Ada Lovelace");

          const nextBtn = page.getByRole("button", { name: "Next" });
          await expect(nextBtn).toBeEnabled({ timeout: 5000 });

          await expectScreenshot(page, {
            name: `onboarding-${theme}-name-step-filled`,
            hide: ['[data-testid="onyx-logo"]'],
          });
        });

        test("LLM setup step", async ({ page }) => {
          await page.addInitScript(
            (t: string) => localStorage.setItem("theme", t),
            theme
          );
          await page.goto("/app");
          await page.waitForLoadState("networkidle");

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
          ).toBeVisible({ timeout: 10000 });
          await expect(page.getByText("Step 2 of 3").first()).toBeVisible();

          const connectLabels = page.getByText("Connect", { exact: true });
          await expect(connectLabels.first()).toBeVisible({ timeout: 10000 });
          await expect(
            page.getByRole("link", { name: "View in Admin Panel" })
          ).toBeVisible();

          await expectScreenshot(page, {
            name: `onboarding-${theme}-llm-setup-step`,
            hide: ['[data-testid="onyx-logo"]'],
          });
        });

        test("Complete step", async ({ page }) => {
          await page.addInitScript(
            (t: string) => localStorage.setItem("theme", t),
            theme
          );
          await page.goto("/app");
          await page.waitForLoadState("networkidle");

          await navigateToCompleteStep(page);

          await expect(page.getByText("Step 3 of 3").first()).toBeVisible();
          await expect(
            page.getByText("Select web search provider").first()
          ).toBeVisible();
          await expect(
            page.getByText("Enable image generation").first()
          ).toBeVisible();
          await expect(
            page.getByText("Invite your team").first()
          ).toBeVisible();

          const finishBtn = page.getByRole("button", {
            name: "Finish Setup",
          });
          await expect(finishBtn).toBeVisible();

          await expectScreenshot(page, {
            name: `onboarding-${theme}-complete-step`,
            hide: ['[data-testid="onyx-logo"]'],
          });
        });

        test("Finish Setup dismisses onboarding", async ({ page }) => {
          await page.addInitScript(
            (t: string) => localStorage.setItem("theme", t),
            theme
          );
          await page.goto("/app");
          await page.waitForLoadState("networkidle");

          await navigateToCompleteStep(page);

          const finishBtn = page.getByRole("button", {
            name: "Finish Setup",
          });
          await expect(finishBtn).toBeVisible({ timeout: 10000 });
          await finishBtn.click();

          await expect(
            page.getByText("Let's take a moment to get you set up.").first()
          ).not.toBeVisible({ timeout: 5000 });

          const chatInput = page.locator("#onyx-chat-input-textarea");
          await expect(chatInput).toBeVisible({ timeout: 10000 });

          await expectScreenshot(page, {
            name: `onboarding-${theme}-post-onboarding`,
            hide: ['[data-testid="onyx-logo"]'],
          });
        });

        test("Full page screenshots", async ({ page }) => {
          await page.addInitScript(
            (t: string) => localStorage.setItem("theme", t),
            theme
          );
          await page.goto("/app");
          await page.waitForLoadState("networkidle");

          await expect(
            page.getByText("Let's take a moment to get you set up.").first()
          ).toBeVisible({ timeout: 15000 });
          await expectScreenshot(page, {
            name: `onboarding-${theme}-full-page-welcome`,
            fullPage: true,
            hide: ['[data-testid="onyx-logo"]'],
          });

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
  });

  // ─── Scenario 2: Admin WITH LLM providers ───────────────────────────
  test.describe("Admin with LLM providers", () => {
    test.beforeEach(async ({ page }) => {
      // Ensure provider exists
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await adminClient.ensurePublicProvider();

      // Create a fresh admin user
      await createFreshAdmin(page);
    });

    test("does not show full onboarding flow", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      await expect(
        page.locator('[aria-label="onboarding-flow"]')
      ).not.toBeVisible({ timeout: 5000 });
    });

    test("shows name prompt when name not set", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const namePrompt = page.locator('[aria-label="non-admin-name-prompt"]');
      await expect(namePrompt).toBeVisible({ timeout: 15000 });
      await expect(
        namePrompt.getByRole("button", { name: "Save" })
      ).toBeVisible();

      await expectElementScreenshot(namePrompt, {
        name: "onboarding-admin-name-prompt",
      });
    });

    test("chat input bar is enabled", async ({ page }) => {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      await expect(page.locator("#onyx-chat-input")).toBeVisible({
        timeout: 15000,
      });

      const chatInput = page.locator("#onyx-chat-input");
      await expect(chatInput).not.toHaveAttribute("aria-disabled", "true");
    });
  });

  // ─── Scenario 3: Non-admin WITHOUT LLM providers ────────────────────
  test.describe("Non-admin without LLM providers", () => {
    test.beforeEach(async ({ page }) => {
      // Delete all providers (as existing admin)
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await deleteAllProviders(adminClient);

      // Create a fresh non-admin user
      await createFreshUser(page);
    });

    test.afterEach(async ({ page }) => {
      // Restore providers
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await adminClient.ensurePublicProvider();
    });

    test("shows NonAdminStep name prompt", async ({ page }) => {
      // loginAsRandomUser already navigates to /app
      const namePrompt = page.locator('[aria-label="non-admin-name-prompt"]');
      await expect(namePrompt).toBeVisible({ timeout: 15000 });
      await expect(
        namePrompt.getByRole("button", { name: "Save" })
      ).toBeVisible();

      await expectElementScreenshot(namePrompt, {
        name: "onboarding-nonadmin-name-prompt",
      });
    });

    test("does NOT show full onboarding flow", async ({ page }) => {
      await expect(
        page.locator('[aria-label="onboarding-flow"]')
      ).not.toBeVisible({ timeout: 5000 });
      await expect(
        page.locator('[aria-label="onboarding-llm-step"]')
      ).not.toBeVisible();
    });

    test("chat input bar is disabled", async ({ page }) => {
      await expect(page.locator("#onyx-chat-input")).toBeVisible({
        timeout: 15000,
      });

      const chatInput = page.locator("#onyx-chat-input");
      await expect(chatInput).toHaveAttribute("aria-disabled", "true");
    });

    test("can save name and see confirmation", async ({ page }) => {
      const namePrompt = page.locator('[aria-label="non-admin-name-prompt"]');
      await expect(namePrompt).toBeVisible({ timeout: 15000 });

      await namePrompt.getByPlaceholder("Your name").fill("Test User");
      await namePrompt.getByRole("button", { name: "Save" }).click();

      const confirmation = page.locator(
        '[aria-label="non-admin-confirmation"]'
      );
      await expect(confirmation).toBeVisible({ timeout: 10000 });

      await expectElementScreenshot(confirmation, {
        name: "onboarding-nonadmin-confirmation",
      });
    });
  });

  // ─── Scenario 4: Non-admin WITH LLM providers ───────────────────────
  test.describe("Non-admin with LLM providers", () => {
    test.beforeEach(async ({ page }) => {
      // Ensure provider exists
      await page.context().clearCookies();
      await loginAs(page, "admin");
      const adminClient = new OnyxApiClient(page.request);
      await adminClient.ensurePublicProvider();

      // Create a fresh non-admin user
      await createFreshUser(page);
    });

    test("shows name prompt when name not set", async ({ page }) => {
      // loginAsRandomUser already navigates to /app
      const namePrompt = page.locator('[aria-label="non-admin-name-prompt"]');
      await expect(namePrompt).toBeVisible({ timeout: 15000 });
    });

    test("chat input bar is enabled", async ({ page }) => {
      await expect(page.locator("#onyx-chat-input")).toBeVisible({
        timeout: 15000,
      });

      const chatInput = page.locator("#onyx-chat-input");
      await expect(chatInput).not.toHaveAttribute("aria-disabled", "true");
    });

    test("after setting name, shows confirmation then no onboarding UI", async ({
      page,
    }) => {
      const namePrompt = page.locator('[aria-label="non-admin-name-prompt"]');
      await expect(namePrompt).toBeVisible({ timeout: 15000 });

      await namePrompt.getByPlaceholder("Your name").fill("E2E User");
      await namePrompt.getByRole("button", { name: "Save" }).click();

      const confirmation = page.locator(
        '[aria-label="non-admin-confirmation"]'
      );
      await expect(confirmation).toBeVisible({ timeout: 10000 });

      await expectElementScreenshot(confirmation, {
        name: "onboarding-nonadmin-with-llm-confirmation",
      });

      await confirmation.getByRole("button").first().click();
      await expect(namePrompt).not.toBeVisible({ timeout: 5000 });
      await expect(confirmation).not.toBeVisible();
    });

    // ── Theme-variant visual regression tests ───────────────────────

    for (const theme of THEMES) {
      test.describe(`Visual regression — ${theme}`, () => {
        test("Non-admin name prompt", async ({ page }) => {
          await page.addInitScript(
            (t: string) => localStorage.setItem("theme", t),
            theme
          );
          await page.goto("/app");
          await page.waitForLoadState("networkidle");

          await expect(
            page.getByText("What should Onyx call you?").first()
          ).toBeVisible({ timeout: 15000 });

          const nameInput = page.getByPlaceholder("Your name");
          await expect(nameInput).toBeVisible();

          const saveBtn = page.getByRole("button", { name: "Save" });
          await expect(saveBtn).toBeVisible();
          await expect(saveBtn).toBeDisabled();

          await expectScreenshot(page, {
            name: `onboarding-${theme}-nonadmin-initial`,
            hide: ['[data-testid="onyx-logo"]'],
          });
        });

        test("Non-admin name filled and saved", async ({ page }) => {
          await page.addInitScript(
            (t: string) => localStorage.setItem("theme", t),
            theme
          );
          await page.goto("/app");
          await page.waitForLoadState("networkidle");

          const nameInput = page.getByPlaceholder("Your name");
          await expect(nameInput).toBeVisible({ timeout: 15000 });
          await nameInput.fill("Jane Doe");

          const saveBtn = page.getByRole("button", { name: "Save" });
          await expect(saveBtn).toBeEnabled();

          await expectScreenshot(page, {
            name: `onboarding-${theme}-nonadmin-name-filled`,
            hide: ['[data-testid="onyx-logo"]'],
          });

          const responsePromise = page.waitForResponse(
            (resp) =>
              resp.url().includes("/api/user/personalization") &&
              resp.request().method() === "PATCH" &&
              resp.status() === 200
          );
          await saveBtn.click();
          await responsePromise;

          await expect(
            page.getByText("What should Onyx call you?").first()
          ).not.toBeVisible({ timeout: 10000 });

          const chatInput = page.locator("#onyx-chat-input-textarea");
          await expect(chatInput).toBeVisible({ timeout: 10000 });

          await expectScreenshot(page, {
            name: `onboarding-${theme}-nonadmin-saved`,
            hide: ['[data-testid="onyx-logo"]'],
          });
        });

        test("Non-admin Enter to save", async ({ page }) => {
          await page.addInitScript(
            (t: string) => localStorage.setItem("theme", t),
            theme
          );
          await page.goto("/app");
          await page.waitForLoadState("networkidle");

          const nameInput = page.getByPlaceholder("Your name");
          await expect(nameInput).toBeVisible({ timeout: 15000 });
          await nameInput.fill("John Doe");

          const responsePromise = page.waitForResponse(
            (resp) =>
              resp.url().includes("/api/user/personalization") &&
              resp.request().method() === "PATCH" &&
              resp.status() === 200
          );
          await nameInput.press("Enter");
          await responsePromise;

          await expect(
            page.getByText("What should Onyx call you?").first()
          ).not.toBeVisible({ timeout: 10000 });
        });
      });
    }
  });
});
