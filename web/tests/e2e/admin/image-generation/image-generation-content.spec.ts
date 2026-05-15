import { test, expect, Page, Locator } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const IMAGE_GENERATION_URL =
  "http://localhost:3000/admin/configuration/image-generation";

// Provider IDs matching constants.ts
const PROVIDERS = [
  { id: "openai_gpt_image_1_5", title: "GPT Image 1.5" },
  { id: "openai_gpt_image_1", title: "GPT Image 1" },
];

// Helper to find a provider card by its aria-label
function getProviderCard(page: Page, providerId: string): Locator {
  return page.getByLabel(`image-gen-provider-${providerId}`, { exact: true });
}

// Helper to open the provider connection modal
async function openProviderModal(
  page: Page,
  providerId: string
): Promise<void> {
  const card = getProviderCard(page, providerId);
  await card.waitFor({ state: "visible", timeout: 10000 });

  // Click the Connect button within the card
  const connectButton = card.getByRole("button", { name: "Connect" });
  await connectButton.waitFor({ state: "visible", timeout: 5000 });
  await connectButton.click();
}

test.describe("Image Generation Provider Configuration", () => {
  test.beforeEach(async ({ page }) => {
    // Log in as admin before each test
    await page.context().clearCookies();
    await loginAs(page, "admin");

    // Navigate to image generation config page
    await page.goto(IMAGE_GENERATION_URL);
    await page.waitForLoadState("networkidle");

    // Wait for page to fully load - look for the section heading
    await page.waitForSelector("text=Image Generation Model", {
      timeout: 20000,
    });

    console.log("[image-gen-test] Page loaded successfully");
  });

  test("should open connection modal for all image generation providers", async ({
    page,
  }) => {
    for (const provider of PROVIDERS) {
      console.log(
        `[image-gen-test] Testing modal open for provider: ${provider.title}`
      );

      // Click Connect on provider card using aria-label
      await openProviderModal(page, provider.id);

      // Verify modal opens with correct title
      // Modal title is "Connect {providerTitle}" for new connections
      const modalDialog = page.getByRole("dialog", {
        name: new RegExp(`connect ${provider.title}`, "i"),
      });
      await expect(modalDialog).toBeVisible({ timeout: 10000 });

      console.log(`[image-gen-test] Modal opened for ${provider.title}`);

      // Close modal by pressing Escape
      await page.keyboard.press("Escape");
      await expect(modalDialog).not.toBeVisible({ timeout: 5000 });

      console.log(`[image-gen-test] Modal closed for ${provider.title}`);
    }

    console.log(
      "[image-gen-test] All provider modals opened and closed successfully"
    );
  });

  test.describe("OpenAI GPT Image 1 Configuration", () => {
    const OPENAI_API_KEY = process.env.OPENAI_API_KEY;

    test.skip(!OPENAI_API_KEY, "OPENAI_API_KEY environment variable not set");

    test.afterEach(async ({ page }) => {
      // Clean up the image generation config created during the test
      const apiClient = new OnyxApiClient(page.request);
      try {
        await apiClient.deleteImageGenerationConfig("openai_gpt_image_1");
        console.log("[image-gen-test] Cleaned up GPT Image 1 config");
      } catch (error) {
        console.warn(
          `[image-gen-test] Failed to clean up GPT Image 1 config: ${error}`
        );
      }
    });

    test.skip("should configure GPT Image 1 with API key", async ({ page }) => {
      // Click Connect on GPT Image 1 card using aria-label
      await openProviderModal(page, "openai_gpt_image_1");

      // Wait for modal to open
      const modalDialog = page.getByRole("dialog", {
        name: /connect gpt image 1/i,
      });
      await expect(modalDialog).toBeVisible({ timeout: 10000 });

      // Enter API key - use getByRole("combobox") to target only the input, not the listbox
      const apiKeyInput = modalDialog.getByRole("combobox");
      await apiKeyInput.waitFor({ state: "visible", timeout: 5000 });
      await apiKeyInput.clear();
      await apiKeyInput.fill(OPENAI_API_KEY!);

      // Close the dropdown by pressing Escape - it intercepts clicks on the Connect button
      await page.keyboard.press("Escape");

      // Click Connect button in modal - scope to the dialog to avoid matching other buttons
      const modalConnectButton = modalDialog.getByRole("button", {
        name: "Connect",
        exact: true,
      });
      await expect(modalConnectButton).toBeEnabled({ timeout: 5000 });
      await modalConnectButton.click();

      console.log(
        "[image-gen-test] Clicked Connect, waiting for validation..."
      );

      // Wait for modal to close (indicates success)
      await expect(modalDialog).not.toBeVisible({ timeout: 30000 });

      console.log(
        "[image-gen-test] Modal closed, verifying provider is configured..."
      );

      // Wait for page to update
      await page.waitForLoadState("networkidle");

      // Verify GPT Image 1 is now configured - should show "Current Default"
      const gptImageCard = getProviderCard(page, "openai_gpt_image_1");
      await expect(
        gptImageCard.getByRole("button", { name: "Current Default" })
      ).toBeVisible({ timeout: 15000 });

      console.log("[image-gen-test] GPT Image 1 configured successfully");
    });
  });
});
