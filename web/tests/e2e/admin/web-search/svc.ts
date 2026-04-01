import type { Page, Locator } from "@playwright/test";

export const WEB_SEARCH_URL = "/admin/configuration/web-search";

export const FAKE_SEARCH_PROVIDERS = {
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

export const FAKE_CONTENT_PROVIDERS = {
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

export function findProviderCard(page: Page, providerLabel: string): Locator {
  return page
    .locator("div.rounded-16")
    .filter({ hasText: providerLabel })
    .first();
}

export function mainContainer(page: Page): Locator {
  return page.locator("[data-main-container]");
}

export async function openProviderModal(
  page: Page,
  providerLabel: string
): Promise<void> {
  const card = findProviderCard(page, providerLabel);
  await card.waitFor({ state: "visible", timeout: 10000 });

  // First try to find the Connect button
  const connectButton = card.getByRole("button", { name: "Connect" });
  if (await connectButton.isVisible({ timeout: 1000 }).catch(() => false)) {
    await connectButton.click();
    return;
  }

  // If no Connect button, click the Edit icon button to update credentials
  const editButton = card.getByRole("button", { name: /^Edit / });
  await editButton.waitFor({ state: "visible", timeout: 5000 });
  await editButton.click();
}

export async function mockWebSearchApis(
  page: Page,
  searchProviders: (typeof FAKE_SEARCH_PROVIDERS)[keyof typeof FAKE_SEARCH_PROVIDERS][],
  contentProviders: (typeof FAKE_CONTENT_PROVIDERS)[keyof typeof FAKE_CONTENT_PROVIDERS][]
): Promise<void> {
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
