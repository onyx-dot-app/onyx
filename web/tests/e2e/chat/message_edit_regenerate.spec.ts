import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser } from "../utils/auth";
import { sendMessage, switchModel } from "../utils/chatActions";

test.describe("Message Edit and Regenerate Tests", () => {
  test.beforeEach(async ({ page }) => {
    // Clear cookies and log in as a random user
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    // Navigate to the chat page
    await page.goto("http://localhost:3000/chat");
    await page.waitForLoadState("networkidle");
  });

  test("Complete message editing functionality", async ({ page }) => {
    // Send initial message
    await sendMessage(page, "What is 2+2?");

    // Test cancel editing
    let userMessage = page.locator("#onyx-human-message").first();
    await userMessage.hover();
    let editButton = userMessage
      .locator('[data-testid="HumanMessage/edit-button"]')
      .first();
    await editButton.click();

    let textarea = userMessage.locator("textarea");
    await textarea.fill("This edit will be cancelled");

    const cancelButton = userMessage.locator('button:has-text("Cancel")');
    await cancelButton.click();

    // Verify original message is preserved
    let messageContent = await userMessage.textContent();
    expect(messageContent).toContain("What is 2+2?");
    expect(messageContent).not.toContain("This edit will be cancelled");

    // Edit the message for real
    await userMessage.hover();
    editButton = userMessage
      .locator('[data-testid="HumanMessage/edit-button"]')
      .first();
    await editButton.click();

    textarea = userMessage.locator("textarea");
    await textarea.fill("What is 3+3?");

    let submitButton = userMessage.locator('button:has-text("Submit")');
    await submitButton.click();

    // Wait for the new AI response to complete
    await page.waitForSelector('[data-testid="AIMessage/copy-button"]', {
      state: "detached",
    });
    await page.waitForSelector('[data-testid="AIMessage/copy-button"]', {
      state: "visible",
      timeout: 30000,
    });

    // Verify edited message is displayed
    messageContent = await page
      .locator("#onyx-human-message")
      .first()
      .textContent();
    expect(messageContent).toContain("What is 3+3?");

    // Verify version switcher appears and shows 2/2
    let messageSwitcher = page.getByTestId("MessageSwitcher/container").first();
    await expect(messageSwitcher).toBeVisible();
    await expect(messageSwitcher).toContainText("2/2");

    // Edit again to create a third version
    userMessage = page.locator("#onyx-human-message").first();
    await userMessage.hover();
    editButton = userMessage
      .locator('[data-testid="HumanMessage/edit-button"]')
      .first();
    await editButton.click();

    textarea = userMessage.locator("textarea");
    await textarea.fill("What is 4+4?");

    submitButton = userMessage.locator('button:has-text("Submit")');
    await submitButton.click();

    // Wait for the new AI response to complete
    await page.waitForSelector('[data-testid="AIMessage/copy-button"]', {
      state: "detached",
    });
    await page.waitForSelector('[data-testid="AIMessage/copy-button"]', {
      state: "visible",
      timeout: 30000,
    });

    // Verify navigation between versions
    // Find the switcher showing "3 / 3"
    let switcherSpan = page.getByTestId("MessageSwitcher/container").first();
    await expect(switcherSpan).toBeVisible();
    await expect(switcherSpan).toContainText("3/3");

    // Navigate to previous version - click the first svg icon's parent (left chevron)
    await switcherSpan
      .locator("..")
      .locator("svg")
      .first()
      .locator("..")
      .click();

    // Check we're now at "2 / 3"
    switcherSpan = page.getByTestId("MessageSwitcher/container").first();
    await expect(switcherSpan).toBeVisible({ timeout: 5000 });
    await expect(switcherSpan).toContainText("2/3");

    // Navigate to first version - re-find the button each time
    await switcherSpan
      .locator("..")
      .locator("svg")
      .first()
      .locator("..")
      .click();

    // Check we're now at "1 / 3"
    switcherSpan = page.getByTestId("MessageSwitcher/container").first();
    await expect(switcherSpan).toBeVisible({ timeout: 5000 });
    await expect(switcherSpan).toContainText("1/3");

    // Navigate forward using next button - click the last svg icon's parent (right chevron)
    await switcherSpan
      .locator("..")
      .locator("svg")
      .last()
      .locator("..")
      .click();

    // Check we're back at "2 / 3"
    switcherSpan = page.getByTestId("MessageSwitcher/container").first();
    await expect(switcherSpan).toBeVisible({ timeout: 5000 });
    await expect(switcherSpan).toContainText("2/3");
  });

  test("Message regeneration with model selection", async ({ page }) => {
    // make sure we're using something other than GPT 4o Mini, otherwise the below
    // will fail since
    // `const gpt4oMiniOption = page.locator("text=/.*GPT.?4o.?Mini.*/i").first();`
    // will find the currently selected model
    await switchModel(page, "GPT 4o");

    // Send initial message
    await sendMessage(page, "hi! Respond with no more than a sentence");
    await page.waitForSelector('[data-testid="onyx-ai-message"]');
    await page.waitForTimeout(3000);

    // Capture the original AI response text (just the message content, not buttons/switcher)
    const aiMessage = page.locator('[data-testid="onyx-ai-message"]').first();
    // Target the actual message content div (the one with select-text class)
    const messageContent = aiMessage.locator(".select-text").first();
    const originalResponseText = await messageContent.textContent();

    // Hover over AI message to show regenerate button
    await aiMessage.hover();

    // Click regenerate button using its data-testid
    const regenerateButton = aiMessage.getByTestId("AIMessage/regenerate");
    await regenerateButton.click();

    // Wait for dropdown to appear and select GPT-4o-mini
    await page.waitForTimeout(500);

    // Look for the GPT-4o-mini option in the dropdown
    const gpt4oMiniOption = page.locator("text=/.*GPT.?4o.?Mini.*/i").first();
    await gpt4oMiniOption.click();

    // Wait for regeneration to complete by waiting for feedback buttons to appear
    // The feedback buttons (copy, like, dislike, regenerate) appear when streaming is complete
    await page.waitForSelector('[data-testid="AIMessage/regenerate"]', {
      state: "visible",
      timeout: 15000,
    });

    // Verify version switcher appears showing "2 / 2"
    const messageSwitcher = page
      .getByTestId("MessageSwitcher/container")
      .first();
    await expect(messageSwitcher).toBeVisible({ timeout: 5000 });
    await expect(messageSwitcher).toContainText("2/2");

    // Navigate to previous version
    await messageSwitcher
      .locator("..")
      .locator("svg")
      .first()
      .locator("..")
      .click();
    await page.waitForTimeout(1000);

    // Verify we're at "1 / 2"
    let switcherSpan = page.getByTestId("MessageSwitcher/container").first();
    await expect(switcherSpan).toBeVisible({ timeout: 5000 });
    await expect(switcherSpan).toContainText("1/2");

    // Verify we're back to the original response
    const firstVersionText = await messageContent.textContent();
    expect(firstVersionText).toBe(originalResponseText);

    // Navigate back to regenerated version
    await switcherSpan
      .locator("..")
      .locator("svg")
      .last()
      .locator("..")
      .click();
    await page.waitForTimeout(1000);

    // Verify we're back at "2 / 2"
    switcherSpan = page.getByTestId("MessageSwitcher/container").first();
    await expect(switcherSpan).toBeVisible({ timeout: 5000 });
    await expect(switcherSpan).toContainText("2/2");
  });
});
