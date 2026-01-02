import { test, expect } from "@chromatic-com/playwright";
import { Route } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";

test.describe("First user onboarding flow", () => {
  test("completes onboarding wizard and unlocks chat input", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name !== "no-auth",
      "Onboarding flow requires a clean session without preset auth state"
    );

    // Track whether we've "created" a provider for this run.
    let providerCreated = false;

    // Force an empty provider list at first so onboarding shows, then return
    // a stub provider after the Connect flow completes.
    const providerListResponder = async (route: Route) => {
      if (route.request().method() !== "GET") {
        await route.continue();
        return;
      }
      const body = providerCreated
        ? JSON.stringify([
            {
              id: 1,
              name: "OpenAI",
              provider: "openai",
              is_default_provider: true,
              default_model_name: "gpt-4o",
              model_configurations: [{ name: "gpt-4o", is_visible: true }],
            },
          ])
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
          providerCreated = true;
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              id: 1,
              name: "OpenAI",
              provider: "openai",
              is_default_provider: true,
              default_model_name: "gpt-4o",
              model_configurations: [{ name: "gpt-4o", is_visible: true }],
            }),
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

    await page.goto("/chat");
    await page.waitForLoadState("networkidle");

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

    const onboardingTitle = page
      .getByText("Let's take a moment to get you set up.")
      .first();
    await expect(onboardingTitle).toBeVisible({ timeout: 20000 });

    const letsGoButton = page.getByRole("button", { name: "Let's Go" });
    await expect(letsGoButton).toBeEnabled();
    await letsGoButton.click();

    await expect(page.getByText("Step 1 of 3")).toBeVisible();
    await expect(page.getByText("What should Onyx call you?")).toBeVisible();

    const nameInput = page.getByPlaceholder("Your name").first();
    await nameInput.fill("Playwright Tester");
    await expect(nameInput).toHaveValue("Playwright Tester");

    const nextButton = page.getByRole("button", { name: "Next", exact: true });
    await expect(nextButton).toBeEnabled();
    await nextButton.click();

    await expect(
      page.getByText("Almost there! Connect your models to start chatting.")
    ).toBeVisible();
    await expect(page.getByText("Step 2 of 3")).toBeVisible();

    const providerCards = [
      { title: "GPT", subtitle: "OpenAI" },
      { title: "Claude", subtitle: "Anthropic" },
      { title: "Azure OpenAI", subtitle: "Microsoft Azure Cloud" },
      { title: "Amazon Bedrock", subtitle: "AWS" },
      { title: "Gemini", subtitle: "Google Cloud Vertex AI" },
      { title: "OpenRouter", subtitle: "OpenRouter" },
      { title: "Ollama", subtitle: "Ollama" },
      { title: "Custom LLM Provider", subtitle: "LiteLLM Compatible APIs" },
    ];

    for (const provider of providerCards) {
      await expect(
        page
          .getByRole("button", {
            name: new RegExp(`${provider.title}.*${provider.subtitle}`, "i"),
          })
          .first()
      ).toBeVisible({ timeout: 20000 });
    }

    const openaiCard = page
      .getByRole("button", { name: /GPT.*OpenAI/i })
      .first();
    await openaiCard.click();

    const providerModal = page.getByRole("dialog", { name: /Set up GPT/i });
    await expect(providerModal).toBeVisible({ timeout: 15000 });

    const apiKeyInput = page
      .getByLabel("API Key", { exact: false })
      .or(page.locator('input[type="password"]').first());
    await apiKeyInput.fill("sk-onboarding-test-key");

    await page.getByRole("button", { name: "Connect" }).click();

    await expect(providerModal).toBeHidden({ timeout: 15000 });

    await expect(nextButton).toBeEnabled({ timeout: 10000 });
    await nextButton.click();

    const completionHeading = page.getByText(
      "You're all set, review the optional settings or click Finish Setup"
    );
    await expect(completionHeading).toBeVisible();
    await expect(page.getByText("Step 3 of 3")).toBeVisible();

    const checklistItems = [
      "Select web search provider",
      "Enable image generation",
      "Invite your team",
    ];
    for (const item of checklistItems) {
      await expect(page.getByText(item)).toBeVisible();
    }

    const finishSetupButton = page.getByRole("button", {
      name: "Finish Setup",
    });
    await finishSetupButton.click();
    await expect(finishSetupButton).toBeHidden({ timeout: 5000 });

    await expect(page.getByText("Connect your LLM models")).toHaveCount(0);

    const chatInput = page.locator("#onyx-chat-input-textarea");
    await chatInput.waitFor({ state: "visible", timeout: 10000 });
    await chatInput.fill("Hello from onboarding");
    await expect(chatInput).toHaveValue("Hello from onboarding");
    await chatInput.fill("");
  });
});
