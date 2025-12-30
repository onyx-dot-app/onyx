import { test, expect } from "@chromatic-com/playwright";
import { Route, Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";

/**
 * Helper to set up common mocks for LLM provider tests
 */
async function setupProviderMocks(page: Page) {
  // Track whether we've "created" a provider for this run.
  let providerCreated = false;
  let createdProvider: any = null;

  // Force an empty provider list at first so onboarding shows, then return
  // a stub provider after the Connect flow completes.
  const providerListResponder = async (route: Route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    const body =
      providerCreated && createdProvider
        ? JSON.stringify([createdProvider])
        : "[]";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body,
    });
  };

  await page.route("**/api/llm/provider", providerListResponder);
  await page.route("**/llm/provider", providerListResponder);

  // Mock provider creation/update endpoints so fake keys still succeed.
  await page.route(
    "**/api/admin/llm/provider?is_creation=true",
    async (route) => {
      if (route.request().method() === "PUT") {
        const body = JSON.parse(route.request().postData() || "{}");
        providerCreated = true;
        createdProvider = {
          id: 1,
          name: body.name || "Test Provider",
          provider: body.provider || "openai",
          is_default_provider: true,
          default_model_name: body.default_model_name || "gpt-4o",
          model_configurations: body.model_configurations || [
            { name: "gpt-4o", is_visible: true },
          ],
        };
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(createdProvider),
        });
        return;
      }
      await route.continue();
    }
  );

  await page.route("**/api/admin/llm/provider/*/default", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "{}",
      });
      return;
    }
    await route.continue();
  });

  await page.route(
    (url) => url.pathname.endsWith("/api/admin/llm/test"),
    async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ok: true }),
        });
      } else {
        await route.continue();
      }
    }
  );

  return {
    setProviderCreated: (value: boolean) => {
      providerCreated = value;
    },
  };
}

/**
 * Helper to navigate to the LLM setup step in onboarding
 */
async function navigateToLLMSetup(page: Page) {
  await page.context().clearCookies();
  await loginAs(page, "admin");

  // Reset the admin user's personalization to ensure onboarding starts from step 1
  await page.evaluate(async () => {
    await fetch("/api/user/personalization", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ name: "" }),
    });
  });

  await page.goto("http://localhost:3000/chat");
  await page.waitForLoadState("networkidle");

  // Dismiss any team modals
  const dismissNewTeamModal = async () => {
    const continueButton = page
      .getByRole("button", { name: /Continue with new team/i })
      .first();
    if ((await continueButton.count()) > 0) {
      await continueButton.click();
      return true;
    }

    const tryOnyxButton = page
      .getByRole("button", { name: /Try Onyx while waiting/i })
      .first();
    if ((await tryOnyxButton.count()) > 0) {
      await tryOnyxButton.click();
      return true;
    }
    return false;
  };
  for (let attempt = 0; attempt < 3; attempt++) {
    const dismissed = await dismissNewTeamModal();
    if (dismissed) {
      break;
    }
    await page.waitForTimeout(250);
  }

  // Wait for onboarding
  const onboardingTitle = page
    .getByText("Let's take a moment to get you set up.")
    .first();
  await expect(onboardingTitle).toBeVisible({ timeout: 20000 });

  // Click Let's Go
  const letsGoButton = page.getByRole("button", { name: "Let's Go" });
  await expect(letsGoButton).toBeEnabled();
  await letsGoButton.click();

  // Fill in name
  const nameInput = page.getByPlaceholder("Your name").first();
  await nameInput.fill("Playwright Tester");

  // Click Next to go to LLM setup
  const nextButton = page.getByRole("button", { name: "Next", exact: true });
  await expect(nextButton).toBeEnabled();
  await nextButton.click();

  // Wait for LLM setup step
  await expect(
    page.getByText("Almost there! Connect your models to start chatting.")
  ).toBeVisible();
}

test.describe("Onboarding LLM Provider Forms", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(
      testInfo.project.name !== "no-auth",
      "Onboarding flow requires a clean session without preset auth state"
    );
  });

  test("OpenAI form validates and submits correctly", async ({ page }) => {
    await setupProviderMocks(page);
    await navigateToLLMSetup(page);

    // Click OpenAI card
    const openaiCard = page
      .getByRole("button", { name: /GPT.*OpenAI/i })
      .first();
    await openaiCard.click();

    // Wait for modal
    const providerModal = page.getByRole("dialog", { name: /Set up GPT/i });
    await expect(providerModal).toBeVisible({ timeout: 15000 });

    // Verify form fields are present
    await expect(page.getByLabel("API Key", { exact: false })).toBeVisible();
    await expect(page.getByText("Default Model")).toBeVisible();

    // Fill API key
    const apiKeyInput = page.locator('input[type="password"]').first();
    await apiKeyInput.fill("sk-test-key-12345");

    // Submit
    await page.getByRole("button", { name: "Connect" }).click();

    // Modal should close on success
    await expect(providerModal).toBeHidden({ timeout: 15000 });
  });

  test("Anthropic form validates and submits correctly", async ({ page }) => {
    await setupProviderMocks(page);
    await navigateToLLMSetup(page);

    // Click Anthropic card
    const anthropicCard = page
      .getByRole("button", { name: /Claude.*Anthropic/i })
      .first();
    await anthropicCard.click();

    // Wait for modal
    const providerModal = page.getByRole("dialog", { name: /Set up Claude/i });
    await expect(providerModal).toBeVisible({ timeout: 15000 });

    // Verify form fields are present
    await expect(page.getByLabel("API Key", { exact: false })).toBeVisible();
    await expect(page.getByText("Default Model")).toBeVisible();

    // Fill API key
    const apiKeyInput = page.locator('input[type="password"]').first();
    await apiKeyInput.fill("sk-ant-test-key-12345");

    // Submit
    await page.getByRole("button", { name: "Connect" }).click();

    // Modal should close on success
    await expect(providerModal).toBeHidden({ timeout: 15000 });
  });

  test("Ollama form has tab switching", async ({ page }) => {
    await setupProviderMocks(page);
    await navigateToLLMSetup(page);

    // Click Ollama card
    const ollamaCard = page
      .getByRole("button", { name: /Ollama.*Ollama/i })
      .first();
    await ollamaCard.click();

    // Wait for modal
    const providerModal = page.getByRole("dialog", { name: /Set up Ollama/i });
    await expect(providerModal).toBeVisible({ timeout: 15000 });

    // Verify tabs are present
    await expect(
      page.getByRole("tab", { name: "Self-hosted Ollama" })
    ).toBeVisible();
    await expect(page.getByRole("tab", { name: "Ollama Cloud" })).toBeVisible();

    // Self-hosted tab should be active by default
    await expect(page.getByLabel("API Base URL")).toBeVisible();

    // Switch to cloud tab
    await page.getByRole("tab", { name: "Ollama Cloud" }).click();

    // Should show API key field
    await expect(page.getByLabel("API Key")).toBeVisible();

    // Close modal
    await page.getByRole("button", { name: "Cancel" }).click();
  });

  test("Azure form validates target URI", async ({ page }) => {
    await setupProviderMocks(page);
    await navigateToLLMSetup(page);

    // Click Azure card
    const azureCard = page
      .getByRole("button", { name: /Azure OpenAI.*Microsoft Azure/i })
      .first();
    await azureCard.click();

    // Wait for modal
    const providerModal = page.getByRole("dialog", {
      name: /Set up Azure OpenAI/i,
    });
    await expect(providerModal).toBeVisible({ timeout: 15000 });

    // Verify form fields are present
    await expect(page.getByLabel("Target URI")).toBeVisible();
    await expect(page.getByLabel("API Key", { exact: false })).toBeVisible();

    // Close modal
    await page.getByRole("button", { name: "Cancel" }).click();
  });

  test("Bedrock form has auth method tabs", async ({ page }) => {
    await setupProviderMocks(page);
    await navigateToLLMSetup(page);

    // Click Bedrock card
    const bedrockCard = page
      .getByRole("button", { name: /Amazon Bedrock.*AWS/i })
      .first();
    await bedrockCard.click();

    // Wait for modal
    const providerModal = page.getByRole("dialog", {
      name: /Set up Amazon Bedrock/i,
    });
    await expect(providerModal).toBeVisible({ timeout: 15000 });

    // Verify auth method tabs are present
    await expect(page.getByRole("tab", { name: "IAM Role" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Access Key" })).toBeVisible();
    await expect(
      page.getByRole("tab", { name: "Long-term API Key" })
    ).toBeVisible();

    // Verify region selector is present
    await expect(page.getByLabel("AWS Region")).toBeVisible();

    // Switch to Access Key tab
    await page.getByRole("tab", { name: "Access Key" }).click();

    // Should show access key fields
    await expect(page.getByLabel("AWS Access Key ID")).toBeVisible();
    await expect(page.getByLabel("AWS Secret Access Key")).toBeVisible();

    // Close modal
    await page.getByRole("button", { name: "Cancel" }).click();
  });

  test("Custom provider form has all required fields", async ({ page }) => {
    await setupProviderMocks(page);
    await navigateToLLMSetup(page);

    // Click Custom LLM Provider card
    const customCard = page
      .getByRole("button", { name: /Custom LLM Provider.*LiteLLM/i })
      .first();
    await customCard.click();

    // Wait for modal
    const providerModal = page.getByRole("dialog", {
      name: /Set up Custom LLM Provider/i,
    });
    await expect(providerModal).toBeVisible({ timeout: 15000 });

    // Verify form fields are present
    await expect(page.getByLabel("Provider Name")).toBeVisible();
    await expect(page.getByText("API Base URL")).toBeVisible();
    await expect(page.getByText("API Version")).toBeVisible();
    await expect(page.getByText("API Key")).toBeVisible();
    await expect(page.getByText("Additional Configs")).toBeVisible();
    await expect(page.getByText("Model Configs")).toBeVisible();
    await expect(page.getByLabel("Default Model")).toBeVisible();

    // Close modal
    await page.getByRole("button", { name: "Cancel" }).click();
  });

  test("Provider cards show connected state after setup", async ({ page }) => {
    await setupProviderMocks(page);
    await navigateToLLMSetup(page);

    // Setup OpenAI
    const openaiCard = page
      .getByRole("button", { name: /GPT.*OpenAI/i })
      .first();
    await openaiCard.click();

    // Fill and submit
    const apiKeyInput = page.locator('input[type="password"]').first();
    await apiKeyInput.fill("sk-test-key-12345");
    await page.getByRole("button", { name: "Connect" }).click();

    // Wait for modal to close
    await expect(page.getByRole("dialog")).toBeHidden({ timeout: 15000 });

    // Verify OpenAI card now shows connected state (green checkmark)
    await expect(
      page
        .locator('[data-testid="check-circle"]')
        .or(page.locator(".stroke-status-success-05"))
    ).toBeVisible({ timeout: 5000 });
  });
});
