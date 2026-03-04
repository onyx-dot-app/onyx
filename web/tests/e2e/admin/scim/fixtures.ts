/**
 * Playwright fixtures for SCIM admin UI tests.
 *
 * Provides:
 * - Authenticated admin page
 * - Stateful mock for the SCIM token endpoint
 *   (GET starts as 404; POST creates a token and flips GET to 200)
 */

import { test as base, expect, Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import type { ScimTokenResponse } from "@/app/admin/scim/interfaces";

// ---------------------------------------------------------------------------
// Fixture control interface
// ---------------------------------------------------------------------------

interface MockTokenControl {
  /** Pre-seed the mock so GET returns an existing token (200). */
  seedToken: () => ScimTokenResponse;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function authenticateAdmin(page: Page): Promise<void> {
  await page.context().clearCookies();
  await loginAs(page, "admin");
}

function jsonResponse(data: unknown, status = 200) {
  return {
    status,
    contentType: "application/json",
    body: JSON.stringify(data),
  };
}

// ---------------------------------------------------------------------------
// Extended test fixture
// ---------------------------------------------------------------------------

export const test = base.extend<{
  adminPage: Page;
  mockTokenEndpoint: MockTokenControl;
}>({
  adminPage: async ({ page }, use) => {
    await authenticateAdmin(page);
    await use(page);
  },

  mockTokenEndpoint: async ({ adminPage }, use) => {
    let currentToken: ScimTokenResponse | null = null;
    let tokenCounter = 0;

    function makeToken(): { token: ScimTokenResponse; rawToken: string } {
      tokenCounter++;
      const rawToken = `scim_test_token_${tokenCounter}_${Date.now()}`;
      const token: ScimTokenResponse = {
        id: tokenCounter,
        name: "default",
        token_display: rawToken.slice(0, 16) + "...",
        is_active: true,
        created_at: new Date().toISOString(),
        last_used_at: null,
        idp_domain: null,
      };
      return { token, rawToken };
    }

    await adminPage.route(
      "**/api/admin/enterprise-settings/scim/token",
      async (route) => {
        const method = route.request().method();

        if (method === "GET") {
          if (currentToken) {
            await route.fulfill(jsonResponse(currentToken));
          } else {
            await route.fulfill(jsonResponse({ detail: "Not found" }, 404));
          }
        } else if (method === "POST") {
          const { token, rawToken } = makeToken();
          currentToken = token;
          await route.fulfill(jsonResponse({ ...token, raw_token: rawToken }));
        } else {
          await route.continue();
        }
      }
    );

    await use({
      seedToken: () => {
        const { token } = makeToken();
        currentToken = token;
        return token;
      },
    });
  },
});

export { expect };

// ---------------------------------------------------------------------------
// Navigation helper
// ---------------------------------------------------------------------------

export async function gotoScimPage(adminPage: Page): Promise<void> {
  await adminPage.goto("/admin/scim");
  await adminPage.waitForLoadState("networkidle");
  await adminPage.waitForSelector("text=SCIM", { timeout: 15000 });
}
