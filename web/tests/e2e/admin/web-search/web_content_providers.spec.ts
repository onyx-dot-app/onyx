import { test, expect, Page, Locator } from "@playwright/test";
import { loginAs } from "../../utils/auth";

const WEB_SEARCH_URL = "/admin/configuration/web-search";

// Helper to find a provider card by its label text
async function findProviderCard(
  page: Page,
  providerLabel: string
): Promise<Locator> {
  const card = page
    .locator("div.rounded-16")
    .filter({ hasText: providerLabel })
    .first();
  return card;
}

// Helper to open the provider setup modal - clicks Connect if available, otherwise clicks the Edit icon
async function openProviderModal(
  page: Page,
  providerLabel: string
): Promise<void> {
  const card = await findProviderCard(page, providerLabel);
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

test.describe("Web Content Provider Configuration", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    await page.goto(WEB_SEARCH_URL);
    await page.waitForLoadState("networkidle");

    // Wait for page to fully load
    await page.waitForSelector("text=Web Crawler", { timeout: 20000 });

    console.log("[web-content-test] Page loaded successfully");
  });

  test.describe("Firecrawl Provider", () => {
    const FIRECRAWL_API_KEY = process.env.FIRECRAWL_API_KEY;

    test.skip(
      !FIRECRAWL_API_KEY,
      "FIRECRAWL_API_KEY environment variable not set"
    );

    test("should configure Firecrawl as web crawler", async ({ page }) => {
      // Click Connect on the Firecrawl card (or key icon if already configured)
      await openProviderModal(page, "Firecrawl");

      const modalDialog = page.getByRole("dialog");
      await expect(modalDialog).toBeVisible({ timeout: 10000 });
      await expect(
        page.getByText("Set up Firecrawl", { exact: false })
      ).toBeVisible();

      // Firecrawl has a base URL field (shown first) and API key
      const baseUrlInput = page.locator('input[placeholder="https://"]');
      await baseUrlInput.waitFor({ state: "visible", timeout: 5000 });
      // Don't check value - it might have a custom value from previous config

      // Enter API key - clear first in case modal opened with masked credentials
      const apiKeyInput = page.locator('input[type="password"]');
      await apiKeyInput.waitFor({ state: "visible", timeout: 5000 });
      await apiKeyInput.clear();
      await apiKeyInput.fill(FIRECRAWL_API_KEY!);

      const modalConnectButton = modalDialog.getByRole("button", {
        name: "Connect",
        exact: true,
      });
      await expect(modalConnectButton).toBeEnabled({ timeout: 5000 });
      await modalConnectButton.click();

      console.log(
        "[web-content-test] Clicked Connect, waiting for validation..."
      );

      await expect(modalDialog).not.toBeVisible({ timeout: 30000 });

      console.log(
        "[web-content-test] Modal closed, verifying Firecrawl is active..."
      );

      await page.waitForLoadState("networkidle");

      const firecrawlCard = await findProviderCard(page, "Firecrawl");
      await expect(
        firecrawlCard.getByRole("button", { name: "Current Crawler" })
      ).toBeVisible({ timeout: 15000 });

      console.log("[web-content-test] Firecrawl configured successfully");
    });

    test("should switch back to Onyx Web Crawler from Firecrawl", async ({
      page,
    }) => {
      // First, ensure Firecrawl is configured and active
      const firecrawlCard = await findProviderCard(page, "Firecrawl");
      await firecrawlCard.waitFor({ state: "visible", timeout: 10000 });

      const connectButton = firecrawlCard.getByRole("button", {
        name: "Connect",
      });
      const setDefaultButton = firecrawlCard.getByRole("button", {
        name: "Set as Default",
      });

      // Only configure if Connect button is visible (not already configured)
      if (await connectButton.isVisible()) {
        await connectButton.click();

        const modalDialog = page.getByRole("dialog");
        await expect(modalDialog).toBeVisible({ timeout: 10000 });
        await expect(
          page.getByText("Set up Firecrawl", { exact: false })
        ).toBeVisible();

        // Enter API key - clear first in case modal opened with masked credentials
        const apiKeyInput = page.locator('input[type="password"]');
        await apiKeyInput.waitFor({ state: "visible", timeout: 5000 });
        await apiKeyInput.clear();
        await apiKeyInput.fill(FIRECRAWL_API_KEY!);

        await modalDialog
          .getByRole("button", { name: "Connect", exact: true })
          .click();
        await expect(modalDialog).not.toBeVisible({ timeout: 30000 });
        await page.waitForLoadState("networkidle");
      } else if (await setDefaultButton.isVisible()) {
        // If already configured but not active, set as default
        await setDefaultButton.click();
        await page.waitForLoadState("networkidle");
      }

      // Verify Firecrawl is now the current crawler
      const updatedFirecrawlCard = await findProviderCard(page, "Firecrawl");
      await expect(
        updatedFirecrawlCard.getByRole("button", { name: "Current Crawler" })
      ).toBeVisible({ timeout: 15000 });

      console.log(
        "[web-content-test] Firecrawl configured, now switching to Onyx Web Crawler..."
      );

      // Switch to Onyx Web Crawler
      const onyxCrawlerCard = await findProviderCard(page, "Onyx Web Crawler");
      await onyxCrawlerCard.waitFor({ state: "visible", timeout: 10000 });

      const onyxSetDefault = onyxCrawlerCard.getByRole("button", {
        name: "Set as Default",
      });

      if (await onyxSetDefault.isVisible()) {
        await onyxSetDefault.click();
        await page.waitForLoadState("networkidle");
      }

      await expect(
        onyxCrawlerCard.getByRole("button", { name: "Current Crawler" })
      ).toBeVisible({ timeout: 15000 });

      console.log("[web-content-test] Switched back to Onyx Web Crawler");
    });
  });
});
