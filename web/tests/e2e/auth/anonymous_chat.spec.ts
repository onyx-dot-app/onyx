import { Page, test, expect } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";

// Regression coverage for the self-hosted "anonymous chat enabled but can't chat
// as anonymous user" bug: when an admin enables anonymous chat, a logged-out
// visitor should reach the chat surface (/app) instead of being redirected to
// the login page.

// Toggle the global anonymous-chat setting via the admin API, mirroring the
// admin UI's read-modify-write (web/src/refresh-pages/admin/ChatPreferencesPage.tsx).
// `page` must be authenticated as an admin.
async function setAnonymousChatEnabled(
  page: Page,
  enabled: boolean
): Promise<void> {
  const getRes = await page.request.get("/api/settings");
  expect(getRes.ok()).toBe(true);
  const current = await getRes.json();

  const putRes = await page.request.put("/api/admin/settings", {
    data: { ...current, anonymous_user_enabled: enabled },
  });
  expect(putRes.ok()).toBe(true);
}

// @exclusive: mutates the global `anonymous_user_enabled` setting, which is
// shared across the single-tenant backend, so it must run serially in isolation.
test.describe("Anonymous chat access @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test.afterEach(async ({ page }) => {
    // Restore the default (disabled) so other suites start from a clean state.
    await loginAs(page, "admin");
    await setAnonymousChatEnabled(page, false);
  });

  test("logged-out visitor is redirected to login when anonymous chat is disabled", async ({
    page,
  }) => {
    await setAnonymousChatEnabled(page, false);
    await page.context().clearCookies();

    await page.goto("/app");
    await page.waitForLoadState("networkidle");

    await expect(page).toHaveURL(/\/auth\/login/);

    // No anonymous user is synthesized when the setting is off.
    const me = await page.request.get("/api/me");
    expect(me.ok()).toBe(false);
  });

  test("logged-out visitor reaches chat as anonymous user when enabled", async ({
    page,
  }) => {
    await setAnonymousChatEnabled(page, true);
    await page.context().clearCookies();

    await page.goto("/app");
    await page.waitForLoadState("networkidle");

    // The cookie-less visitor stays on the chat surface instead of being bounced
    // to login.
    await expect(page).toHaveURL(/\/app(\/|\?|$)/);
    await expect(page).not.toHaveURL(/\/auth\/login/);

    // The backend serves the synthesized anonymous user.
    const me = await page.request.get("/api/me");
    expect(me.ok()).toBe(true);
    const body = await me.json();
    expect(body.is_anonymous_user).toBe(true);
  });

  test("'continue as guest' on the login page leads to chat when enabled", async ({
    page,
  }) => {
    await setAnonymousChatEnabled(page, true);
    await page.context().clearCookies();

    await page.goto("/auth/login");
    await page.waitForLoadState("networkidle");

    const guestLink = page.getByRole("link", { name: /continue as guest/i });
    await expect(guestLink).toBeVisible();
    await guestLink.click();

    await expect(page).toHaveURL(/\/app(\/|\?|$)/);
  });
});
