import { test, expect, Page, Locator } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";

const WEB_SEARCH_URL = "/admin/configuration/web-search";

const FAKE_SEARCH_PROVIDERS = {
  exa: {
    id: 1,
    name: "Exa",
    provider_type: "exa",
    is_active: true,
    config: null,
    has_api_key: true,
  },
  brave: {
    id: 2,
    name: "Brave",
    provider_type: "brave",
    is_active: false,
    config: null,
    has_api_key: true,
  },
};

const FAKE_CONTENT_PROVIDERS = {
  firecrawl: {
    id: 10,
    name: "Firecrawl",
    provider_type: "firecrawl",
    is_active: true,
    config: { base_url: "https://api.firecrawl.dev/v2/scrape" },
    has_api_key: true,
  },
  exa: {
    id: 11,
    name: "Exa",
    provider_type: "exa",
    is_active: false,
    config: null,
    has_api_key: true,
  },
};

function findProviderCard(page: Page, providerLabel: string): Locator {
  return page
    .locator("div.rounded-16")
    .filter({ hasText: providerLabel })
    .first();
}

async function mockWebSearchApis(
  page: Page,
  searchProviders: (typeof FAKE_SEARCH_PROVIDERS)[keyof typeof FAKE_SEARCH_PROVIDERS][],
  contentProviders: (typeof FAKE_CONTENT_PROVIDERS)[keyof typeof FAKE_CONTENT_PROVIDERS][]
) {
  await page.route(
    "**/api/admin/web-search/search-providers",
    async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({ status: 200, json: searchProviders });
      } else {
        await route.continue();
      }
    }
  );

  await page.route(
    "**/api/admin/web-search/content-providers",
    async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({ status: 200, json: contentProviders });
      } else {
        await route.continue();
      }
    }
  );
}

test.describe("Web Search Provider Disconnect", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test.describe("Search Engine Providers", () => {
    test("should disconnect a connected (non-active) search provider", async ({
      page,
    }) => {
      const searchProviders = [
        { ...FAKE_SEARCH_PROVIDERS.exa },
        { ...FAKE_SEARCH_PROVIDERS.brave },
      ];
      await mockWebSearchApis(page, searchProviders, []);

      await page.goto(WEB_SEARCH_URL);
      await page.waitForSelector("text=Search Engine", { timeout: 20000 });

      const braveCard = findProviderCard(page, "Brave");
      await braveCard.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = braveCard.getByRole("button", {
        name: "Disconnect Brave",
      });
      await expect(disconnectButton).toBeVisible();
      await expect(disconnectButton).toBeEnabled();

      // Mock the DELETE to succeed
      await page.route(
        "**/api/admin/web-search/search-providers/2",
        async (route) => {
          if (route.request().method() === "DELETE") {
            await page.unroute("**/api/admin/web-search/search-providers");
            await page.route(
              "**/api/admin/web-search/search-providers",
              async (route) => {
                if (route.request().method() === "GET") {
                  await route.fulfill({
                    status: 200,
                    json: [{ ...FAKE_SEARCH_PROVIDERS.exa }],
                  });
                } else {
                  await route.continue();
                }
              }
            );
            await route.fulfill({ status: 200, json: {} });
          } else {
            await route.continue();
          }
        }
      );

      await disconnectButton.click();

      const confirmDialog = page.getByRole("dialog");
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });
      await expect(confirmDialog).toContainText("Disconnect Brave");

      const confirmButton = confirmDialog.getByRole("button", {
        name: "Disconnect",
      });
      await confirmButton.click();

      await expect(
        braveCard.getByRole("button", { name: "Connect" })
      ).toBeVisible({ timeout: 10000 });
    });

    test("should show replacement dropdown when disconnecting active search provider with alternatives", async ({
      page,
    }) => {
      // Exa is active, Brave is also configured
      const searchProviders = [
        { ...FAKE_SEARCH_PROVIDERS.exa },
        { ...FAKE_SEARCH_PROVIDERS.brave },
      ];
      await mockWebSearchApis(page, searchProviders, []);

      await page.goto(WEB_SEARCH_URL);
      await page.waitForSelector("text=Search Engine", { timeout: 20000 });

      const exaCard = findProviderCard(page, "Exa");
      await exaCard.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = exaCard.getByRole("button", {
        name: "Disconnect Exa",
      });
      await expect(disconnectButton).toBeVisible();
      await expect(disconnectButton).toBeEnabled();

      await disconnectButton.click();

      const confirmDialog = page.getByRole("dialog");
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });
      await expect(confirmDialog).toContainText("Disconnect Exa");

      // Should show replacement dropdown
      await expect(
        confirmDialog.getByText("Choose a replacement")
      ).toBeVisible();

      // Disconnect button should be enabled because first replacement is auto-selected
      const confirmButton = confirmDialog.getByRole("button", {
        name: "Disconnect",
      });
      await expect(confirmButton).toBeEnabled();
    });

    test("should show connect message when disconnecting active search provider with no alternatives", async ({
      page,
    }) => {
      // Only Exa configured and active
      await mockWebSearchApis(page, [{ ...FAKE_SEARCH_PROVIDERS.exa }], []);

      await page.goto(WEB_SEARCH_URL);
      await page.waitForSelector("text=Search Engine", { timeout: 20000 });

      const exaCard = findProviderCard(page, "Exa");
      await exaCard.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = exaCard.getByRole("button", {
        name: "Disconnect Exa",
      });
      await disconnectButton.click();

      const confirmDialog = page.getByRole("dialog");
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });

      // Should show message about connecting another provider
      await expect(
        confirmDialog.getByText("Connect another provider")
      ).toBeVisible();

      // Disconnect button should be enabled
      const confirmButton = confirmDialog.getByRole("button", {
        name: "Disconnect",
      });
      await expect(confirmButton).toBeEnabled();
    });

    test("should not show disconnect button for unconfigured search provider", async ({
      page,
    }) => {
      await mockWebSearchApis(page, [{ ...FAKE_SEARCH_PROVIDERS.exa }], []);

      await page.goto(WEB_SEARCH_URL);
      await page.waitForSelector("text=Search Engine", { timeout: 20000 });

      const braveCard = findProviderCard(page, "Brave");
      await braveCard.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = braveCard.getByRole("button", {
        name: "Disconnect Brave",
      });
      await expect(disconnectButton).not.toBeVisible();
    });
  });

  test.describe("Web Crawler (Content) Providers", () => {
    test("should disconnect a connected (non-active) content provider", async ({
      page,
    }) => {
      // Firecrawl connected but not active, Exa is active
      const contentProviders = [
        { ...FAKE_CONTENT_PROVIDERS.firecrawl, is_active: false },
        { ...FAKE_CONTENT_PROVIDERS.exa, is_active: true },
      ];
      await mockWebSearchApis(page, [], contentProviders);

      await page.goto(WEB_SEARCH_URL);
      await page.waitForSelector("text=Web Crawler", { timeout: 20000 });

      const firecrawlCard = findProviderCard(page, "Firecrawl");
      await firecrawlCard.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = firecrawlCard.getByRole("button", {
        name: "Disconnect Firecrawl",
      });
      await expect(disconnectButton).toBeVisible();
      await expect(disconnectButton).toBeEnabled();

      // Mock the DELETE to succeed
      await page.route(
        "**/api/admin/web-search/content-providers/10",
        async (route) => {
          if (route.request().method() === "DELETE") {
            await page.unroute("**/api/admin/web-search/content-providers");
            await page.route(
              "**/api/admin/web-search/content-providers",
              async (route) => {
                if (route.request().method() === "GET") {
                  await route.fulfill({
                    status: 200,
                    json: [{ ...FAKE_CONTENT_PROVIDERS.exa, is_active: true }],
                  });
                } else {
                  await route.continue();
                }
              }
            );
            await route.fulfill({ status: 200, json: {} });
          } else {
            await route.continue();
          }
        }
      );

      await disconnectButton.click();

      const confirmDialog = page.getByRole("dialog");
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });
      await expect(confirmDialog).toContainText("Disconnect Firecrawl");

      const confirmButton = confirmDialog.getByRole("button", {
        name: "Disconnect",
      });
      await confirmButton.click();

      await expect(
        firecrawlCard.getByRole("button", { name: "Connect" })
      ).toBeVisible({ timeout: 10000 });
    });

    test("should show replacement dropdown when disconnecting active content provider with alternatives", async ({
      page,
    }) => {
      // Firecrawl is active, Exa is also configured
      const contentProviders = [
        { ...FAKE_CONTENT_PROVIDERS.firecrawl },
        { ...FAKE_CONTENT_PROVIDERS.exa },
      ];
      await mockWebSearchApis(page, [], contentProviders);

      await page.goto(WEB_SEARCH_URL);
      await page.waitForSelector("text=Web Crawler", { timeout: 20000 });

      const firecrawlCard = findProviderCard(page, "Firecrawl");
      await firecrawlCard.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = firecrawlCard.getByRole("button", {
        name: "Disconnect Firecrawl",
      });
      await disconnectButton.click();

      const confirmDialog = page.getByRole("dialog");
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });

      // Should show replacement dropdown
      await expect(
        confirmDialog.getByText("Choose a replacement")
      ).toBeVisible();

      // Disconnect should be enabled because first replacement is auto-selected
      const confirmButton = confirmDialog.getByRole("button", {
        name: "Disconnect",
      });
      await expect(confirmButton).toBeEnabled();
    });

    test("should not show disconnect for Onyx Web Crawler (built-in)", async ({
      page,
    }) => {
      await mockWebSearchApis(page, [], []);

      await page.goto(WEB_SEARCH_URL);
      await page.waitForSelector("text=Web Crawler", { timeout: 20000 });

      const onyxCard = findProviderCard(page, "Onyx Web Crawler");
      await onyxCard.waitFor({ state: "visible", timeout: 10000 });

      const disconnectButton = onyxCard.getByRole("button", {
        name: "Disconnect Onyx Web Crawler",
      });
      await expect(disconnectButton).not.toBeVisible();
    });
  });
});
