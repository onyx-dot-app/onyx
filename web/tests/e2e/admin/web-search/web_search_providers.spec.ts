import { test, expect, Page, Locator } from "@playwright/test";
import { loginAs } from "../../utils/auth";

const WEB_SEARCH_URL = "/admin/configuration/web-search";

// Helper to find a provider card by its label text
async function findProviderCard(
  page: Page,
  providerLabel: string
): Promise<Locator> {
  // Find the card containing the provider label - cards are divs with rounded borders
  // The label is in a Text component inside the card
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

test.describe("Web Search Provider Configuration", () => {
  test.beforeEach(async ({ page }) => {
    // Log in as admin before each test
    await page.context().clearCookies();
    await loginAs(page, "admin");

    // Navigate to web search config page
    await page.goto(WEB_SEARCH_URL);
    await page.waitForLoadState("networkidle");

    // Wait for page to fully load - look for the Search Engine section heading
    await page.waitForSelector("text=Search Engine", { timeout: 20000 });

    console.log("[web-search-test] Page loaded successfully");
  });

  test.describe("Exa Provider", () => {
    const EXA_API_KEY = process.env.EXA_API_KEY;

    test.skip(!EXA_API_KEY, "EXA_API_KEY environment variable not set");

    test("should configure Exa as web search provider", async ({ page }) => {
      // Click Connect on the Exa card (or key icon if already configured)
      await openProviderModal(page, "Exa");

      // Wait for modal to open - Modal uses Radix Dialog with role="dialog"
      const modalDialog = page.getByRole("dialog", { name: /set up exa/i });
      await expect(modalDialog).toBeVisible({ timeout: 10000 });

      // Enter API key - clear first in case modal opened with masked credentials
      const apiKeyInput = page.locator('input[type="password"]');
      await apiKeyInput.waitFor({ state: "visible", timeout: 5000 });
      await apiKeyInput.clear();
      await apiKeyInput.fill(EXA_API_KEY!);

      // Click Connect in modal - scope to the dialog to avoid matching other Connect buttons
      const modalConnectButton = modalDialog.getByRole("button", {
        name: "Connect",
        exact: true,
      });
      await expect(modalConnectButton).toBeEnabled({ timeout: 5000 });
      await modalConnectButton.click();

      console.log(
        "[web-search-test] Clicked Connect, waiting for validation..."
      );

      // Wait for modal to close
      await expect(modalDialog).not.toBeVisible({ timeout: 30000 });

      console.log(
        "[web-search-test] Modal closed, verifying provider is active..."
      );

      // Wait for page to update
      await page.waitForLoadState("networkidle");

      // Verify Exa is now the current default - look for "Current Default" button in the Exa card
      const exaCard = await findProviderCard(page, "Exa");
      await expect(
        exaCard.getByRole("button", { name: "Current Default" })
      ).toBeVisible({ timeout: 15000 });

      console.log("[web-search-test] Exa provider configured successfully");
    });
  });

  test.describe("Google PSE Provider", () => {
    const GOOGLE_PSE_API_KEY = process.env.GOOGLE_PSE_API_KEY;
    const GOOGLE_PSE_SEARCH_ENGINE_ID = process.env.GOOGLE_PSE_SEARCH_ENGINE_ID;

    test.skip(
      !GOOGLE_PSE_API_KEY || !GOOGLE_PSE_SEARCH_ENGINE_ID,
      "GOOGLE_PSE_API_KEY or GOOGLE_PSE_SEARCH_ENGINE_ID environment variable not set"
    );

    test("should configure Google PSE as web search provider", async ({
      page,
    }) => {
      // Click Connect on the Google PSE card
      await openProviderModal(page, "Google PSE");

      // Wait for modal to open
      const modalDialog = page.getByRole("dialog", {
        name: /set up google pse/i,
      });
      await expect(modalDialog).toBeVisible({ timeout: 10000 });

      // Google PSE requires both Search Engine ID and API key
      // Enter Search Engine ID
      const searchEngineIdInput = page.locator(
        'input[placeholder="Enter search engine ID"]'
      );
      await searchEngineIdInput.waitFor({ state: "visible", timeout: 5000 });
      await searchEngineIdInput.fill(GOOGLE_PSE_SEARCH_ENGINE_ID!);

      // Enter API key
      const apiKeyInput = page.locator('input[type="password"]');
      await apiKeyInput.waitFor({ state: "visible", timeout: 5000 });
      await apiKeyInput.fill(GOOGLE_PSE_API_KEY!);

      // Click Connect in modal
      const modalConnectButton = modalDialog.getByRole("button", {
        name: "Connect",
        exact: true,
      });
      await expect(modalConnectButton).toBeEnabled({ timeout: 5000 });
      await modalConnectButton.click();

      console.log(
        "[web-search-test] Clicked Connect for Google PSE, waiting for validation..."
      );

      // Wait for modal to close
      await expect(modalDialog).not.toBeVisible({ timeout: 30000 });

      console.log(
        "[web-search-test] Modal closed, verifying Google PSE is active..."
      );

      // Wait for page to update
      await page.waitForLoadState("networkidle");

      // Verify Google PSE is now the current default
      const googleCard = await findProviderCard(page, "Google PSE");
      await expect(
        googleCard.getByRole("button", { name: "Current Default" })
      ).toBeVisible({ timeout: 15000 });

      console.log(
        "[web-search-test] Google PSE provider configured successfully"
      );
    });

    test("should reconnect with stored API key using update key button", async ({
      page,
    }) => {
      // First, configure Google PSE if not already configured
      const googleCard = await findProviderCard(page, "Google PSE");
      await googleCard.waitFor({ state: "visible", timeout: 10000 });

      const connectButton = googleCard.getByRole("button", { name: "Connect" });

      // Only configure if Connect button is visible (not already configured)
      if (await connectButton.isVisible()) {
        await connectButton.click();
        const setupDialog = page.getByRole("dialog", {
          name: /set up google pse/i,
        });
        await expect(setupDialog).toBeVisible({ timeout: 10000 });

        const searchEngineIdInput = page.locator(
          'input[placeholder="Enter search engine ID"]'
        );
        await searchEngineIdInput.waitFor({ state: "visible", timeout: 5000 });
        await searchEngineIdInput.fill(GOOGLE_PSE_SEARCH_ENGINE_ID!);

        const apiKeyInput = page.locator('input[type="password"]');
        await apiKeyInput.waitFor({ state: "visible", timeout: 5000 });
        await apiKeyInput.fill(GOOGLE_PSE_API_KEY!);

        await setupDialog
          .getByRole("button", { name: "Connect", exact: true })
          .click();
        await expect(setupDialog).not.toBeVisible({ timeout: 30000 });
        await page.waitForLoadState("networkidle");
      }

      console.log(
        "[web-search-test] Google PSE configured, now testing update key button..."
      );

      // Now click the Edit icon button
      const updatedGoogleCard = await findProviderCard(page, "Google PSE");
      const editButton = updatedGoogleCard.getByRole("button", {
        name: /^Edit /,
      });
      await expect(editButton).toBeVisible({ timeout: 10000 });
      await editButton.click();

      // Modal should open with masked API key
      const modalDialog = page.getByRole("dialog", {
        name: /set up google pse/i,
      });
      await expect(modalDialog).toBeVisible({ timeout: 10000 });

      // Verify the API key input shows masked value
      const apiKeyInput = page.locator('input[type="password"]');
      await apiKeyInput.waitFor({ state: "visible", timeout: 5000 });
      await expect(apiKeyInput).toHaveValue("••••••••••••••••");

      // Immediately click Connect without changing anything
      const modalConnectButton = modalDialog.getByRole("button", {
        name: "Connect",
        exact: true,
      });
      await expect(modalConnectButton).toBeEnabled({ timeout: 5000 });
      await modalConnectButton.click();

      console.log(
        "[web-search-test] Clicked Connect with stored key, waiting for success..."
      );

      // Wait for modal to close (success)
      await expect(modalDialog).not.toBeVisible({ timeout: 30000 });

      console.log(
        "[web-search-test] Modal closed, verifying Google PSE is still active..."
      );

      // Wait for page to update
      await page.waitForLoadState("networkidle");

      // Verify Google PSE is still the current default
      const finalGoogleCard = await findProviderCard(page, "Google PSE");
      await expect(
        finalGoogleCard.getByRole("button", { name: "Current Default" })
      ).toBeVisible({ timeout: 15000 });

      console.log(
        "[web-search-test] Successfully reconnected with stored API key"
      );
    });

    test("should fail when changing search engine ID with stored API key", async ({
      page,
    }) => {
      // First, configure Google PSE if not already configured
      const googleCard = await findProviderCard(page, "Google PSE");
      await googleCard.waitFor({ state: "visible", timeout: 10000 });

      const connectButton = googleCard.getByRole("button", { name: "Connect" });

      // Only configure if Connect button is visible (not already configured)
      if (await connectButton.isVisible()) {
        await connectButton.click();
        const setupDialog = page.getByRole("dialog", {
          name: /set up google pse/i,
        });
        await expect(setupDialog).toBeVisible({ timeout: 10000 });

        const searchEngineIdInput = page.locator(
          'input[placeholder="Enter search engine ID"]'
        );
        await searchEngineIdInput.waitFor({ state: "visible", timeout: 5000 });
        await searchEngineIdInput.fill(GOOGLE_PSE_SEARCH_ENGINE_ID!);

        const apiKeyInput = page.locator('input[type="password"]');
        await apiKeyInput.waitFor({ state: "visible", timeout: 5000 });
        await apiKeyInput.fill(GOOGLE_PSE_API_KEY!);

        await setupDialog
          .getByRole("button", { name: "Connect", exact: true })
          .click();
        await expect(setupDialog).not.toBeVisible({ timeout: 30000 });
        await page.waitForLoadState("networkidle");
      }

      console.log(
        "[web-search-test] Google PSE configured, now testing invalid search engine ID change..."
      );

      // Now click the Edit icon button
      const updatedGoogleCard = await findProviderCard(page, "Google PSE");
      const editButton = updatedGoogleCard.getByRole("button", {
        name: /^Edit /,
      });
      await expect(editButton).toBeVisible({ timeout: 10000 });
      await editButton.click();

      // Modal should open with masked API key
      const modalDialog = page.getByRole("dialog", {
        name: /set up google pse/i,
      });
      await expect(modalDialog).toBeVisible({ timeout: 10000 });

      // Change the search engine ID to an invalid value
      const searchEngineIdInput = page.locator(
        'input[placeholder="Enter search engine ID"]'
      );
      await searchEngineIdInput.waitFor({ state: "visible", timeout: 5000 });
      await searchEngineIdInput.clear();
      await searchEngineIdInput.fill("invalid-search-engine-id");

      // Do NOT change the API key - keep the masked value
      const apiKeyInput = page.locator('input[type="password"]');
      await expect(apiKeyInput).toHaveValue("••••••••••••••••");

      // Click Connect - should fail because search engine ID doesn't match the stored API key
      const modalConnectButton = modalDialog.getByRole("button", {
        name: "Connect",
        exact: true,
      });
      await expect(modalConnectButton).toBeEnabled({ timeout: 5000 });
      await modalConnectButton.click();

      console.log(
        "[web-search-test] Clicked Connect with invalid search engine ID, waiting for error..."
      );

      // Should show error message
      await expect(page.getByText(/failed|invalid|error/i).first()).toBeVisible(
        { timeout: 20000 }
      );

      console.log(
        "[web-search-test] Error message displayed as expected for mismatched search engine ID"
      );
    });
  });

  test.describe("Provider Switching", () => {
    // These tests require both providers to be configured
    const EXA_API_KEY = process.env.EXA_API_KEY;
    const GOOGLE_PSE_API_KEY = process.env.GOOGLE_PSE_API_KEY;
    const GOOGLE_PSE_SEARCH_ENGINE_ID = process.env.GOOGLE_PSE_SEARCH_ENGINE_ID;

    test.skip(
      !EXA_API_KEY || !GOOGLE_PSE_API_KEY || !GOOGLE_PSE_SEARCH_ENGINE_ID,
      "Both EXA and Google PSE credentials required"
    );

    test("should switch between configured providers", async ({ page }) => {
      // First, configure Exa if needed
      const exaCard = await findProviderCard(page, "Exa");
      await exaCard.waitFor({ state: "visible", timeout: 10000 });

      let connectButton = exaCard.getByRole("button", { name: "Connect" });

      // Only configure if Connect button is visible (not already configured)
      if (await connectButton.isVisible()) {
        await connectButton.click();
        const exaDialog = page.getByRole("dialog", { name: /set up exa/i });
        await expect(exaDialog).toBeVisible({ timeout: 10000 });

        const apiKeyInput = page.locator('input[type="password"]');
        await apiKeyInput.waitFor({ state: "visible", timeout: 5000 });
        await apiKeyInput.fill(EXA_API_KEY!);

        await exaDialog
          .getByRole("button", { name: "Connect", exact: true })
          .click();
        await expect(exaDialog).not.toBeVisible({ timeout: 30000 });
        await page.waitForLoadState("networkidle");
      }

      // Configure Google PSE if needed
      const googleCard = await findProviderCard(page, "Google PSE");
      await googleCard.waitFor({ state: "visible", timeout: 10000 });

      connectButton = googleCard.getByRole("button", { name: "Connect" });

      if (await connectButton.isVisible()) {
        await connectButton.click();
        const googleDialog = page.getByRole("dialog", {
          name: /set up google pse/i,
        });
        await expect(googleDialog).toBeVisible({ timeout: 10000 });

        const searchEngineIdInput = page.locator(
          'input[placeholder="Enter search engine ID"]'
        );
        await searchEngineIdInput.waitFor({ state: "visible", timeout: 5000 });
        await searchEngineIdInput.fill(GOOGLE_PSE_SEARCH_ENGINE_ID!);

        const apiKeyInput = page.locator('input[type="password"]');
        await apiKeyInput.waitFor({ state: "visible", timeout: 5000 });
        await apiKeyInput.fill(GOOGLE_PSE_API_KEY!);

        await googleDialog
          .getByRole("button", { name: "Connect", exact: true })
          .click();
        await expect(googleDialog).not.toBeVisible({ timeout: 30000 });
        await page.waitForLoadState("networkidle");
      }

      // Now test switching - click "Set as Default" on whichever is not current
      const exaSetDefault = exaCard.getByRole("button", {
        name: "Set as Default",
      });
      const googleSetDefault = googleCard.getByRole("button", {
        name: "Set as Default",
      });

      if (await exaSetDefault.isVisible()) {
        console.log("[web-search-test] Switching to Exa as default...");
        await exaSetDefault.click();
        await page.waitForLoadState("networkidle");
        await expect(
          exaCard.getByRole("button", { name: "Current Default" })
        ).toBeVisible({ timeout: 15000 });
        console.log("[web-search-test] Successfully switched to Exa");
      } else if (await googleSetDefault.isVisible()) {
        console.log("[web-search-test] Switching to Google PSE as default...");
        await googleSetDefault.click();
        await page.waitForLoadState("networkidle");
        await expect(
          googleCard.getByRole("button", { name: "Current Default" })
        ).toBeVisible({ timeout: 15000 });
        console.log("[web-search-test] Successfully switched to Google PSE");
      }
    });
  });

  // TODO: @jessica - add Serper provider tests
});
