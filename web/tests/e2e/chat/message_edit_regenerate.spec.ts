import { test, expect } from "@playwright/test";
import { loginAsRandomUser } from "../utils/auth";
import { sendMessage, switchModel } from "../utils/chatActions";

test.describe("Message Edit and Regenerate Tests", () => {
  test.beforeEach(async ({ page }) => {
    // Clear cookies and log in as a random user
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    // Navigate to the chat page
    await page.goto("/app");
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
    await page.waitForSelector('[data-testid="AgentMessage/copy-button"]', {
      state: "detached",
    });
    await page.waitForSelector('[data-testid="AgentMessage/copy-button"]', {
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
    await page.waitForSelector('[data-testid="AgentMessage/copy-button"]', {
      state: "detached",
    });
    await page.waitForSelector('[data-testid="AgentMessage/copy-button"]', {
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
    // make sure we're using something other than GPT-4o Mini, otherwise the below
    // will fail since we need to switch to a different model for the test
    await switchModel(page, "GPT-4.1");

    // Send initial message
    await sendMessage(page, "hi! Respond with no more than a sentence");

    // Capture the original AI response text (just the message content, not buttons/switcher)
    const aiMessage = page.locator('[data-testid="onyx-ai-message"]').first();
    // Target the actual message content div (the one with select-text class)
    const messageContent = aiMessage.locator(".select-text").first();
    const originalResponseText = await messageContent.textContent();

    // Hover over AI message to show regenerate button
    await aiMessage.hover();

    // Click regenerate button using its data-testid
    const regenerateButton = aiMessage.getByTestId("AgentMessage/regenerate");
    await regenerateButton.click();

    // Wait for dropdown to appear and select GPT-4o Mini
    await page.waitForSelector('[role="dialog"]', { state: "visible" });

    // Look for the GPT-4o Mini option in the dropdown
    const gpt4oMiniOption = page
      .locator('[role="dialog"]')
      .getByText("GPT-4o Mini", { exact: true })
      .first();
    await gpt4oMiniOption.click();

    // Wait for regeneration to complete by waiting for feedback buttons to appear
    // The feedback buttons (copy, like, dislike, regenerate) appear when streaming is complete
    await page.waitForSelector('[data-testid="AgentMessage/regenerate"]', {
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

    // Verify we're back at "2 / 2"
    switcherSpan = page.getByTestId("MessageSwitcher/container").first();
    await expect(switcherSpan).toBeVisible({ timeout: 5000 });
    await expect(switcherSpan).toContainText("2/2");
  });

  test("Message editing with files", async ({ page }) => {
    const testFileName = `test-edit-${Date.now()}.txt`;
    const testFileContent = "This is a test file for editing with attachments.";
    const buffer = Buffer.from(testFileContent, "utf-8");

    // Trigger the native file dialog by clicking the hidden file input,
    // then intercept it with the filechooser event (same pattern as
    // user_file_attachment.spec.ts).
    const fileInput = page.locator('input[type="file"]').first();
    const fileChooserPromise = page.waitForEvent("filechooser");
    await fileInput.dispatchEvent("click");
    const fileChooser = await fileChooserPromise;

    const uploadResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/api/user/projects/file/upload") &&
        response.request().method() === "POST"
    );

    await fileChooser.setFiles({
      name: testFileName,
      mimeType: "text/plain",
      buffer: buffer,
    });

    const uploadResponse = await uploadResponsePromise;
    expect(uploadResponse.ok()).toBeTruthy();

    // Wait for upload processing to complete and file card to render
    await page.waitForLoadState("networkidle", { timeout: 10000 });
    await expect(page.getByText(testFileName).first()).toBeVisible({
      timeout: 10000,
    });

    // Send a message with the file attached using the shared utility
    await sendMessage(page, "Summarize this file");

    // Verify the file is displayed in the sent human message
    const humanMessage = page.locator("#onyx-human-message").first();

    // Verify message text is displayed
    const messageContent = await humanMessage.textContent();
    expect(messageContent).toContain("Summarize this file");

    // Hover and click the edit button
    await humanMessage.hover();
    const editButton = humanMessage
      .locator('[data-testid="HumanMessage/edit-button"]')
      .first();
    await expect(editButton).toBeVisible();
    await editButton.click();

    // Edit the message text
    const textarea = humanMessage.locator("textarea");
    await textarea.fill("What does this file contain?");

    // Submit the edit
    const submitButton = humanMessage.locator('button:has-text("Submit")');
    await submitButton.click();

    // Wait for the new AI response to complete
    await page.waitForSelector('[data-testid="AgentMessage/copy-button"]', {
      state: "detached",
    });
    await page.waitForSelector('[data-testid="AgentMessage/copy-button"]', {
      state: "visible",
      timeout: 30000,
    });

    // Verify the edited message text is displayed
    const editedHumanMessage = page.locator("#onyx-human-message").first();
    const editedMessageContent = await editedHumanMessage.textContent();
    expect(editedMessageContent).toContain("What does this file contain?");
    expect(editedMessageContent).not.toContain("Summarize this file");

    // Verify the file is still attached after editing
    const editedFileDisplay = editedHumanMessage.locator("#onyx-file");
    await expect(editedFileDisplay).toBeVisible();
    await expect(editedFileDisplay.getByText(testFileName)).toBeVisible();

    // Verify the version switcher shows 2/2 (original + edited)
    const messageSwitcher = page
      .getByTestId("MessageSwitcher/container")
      .first();
    await expect(messageSwitcher).toBeVisible();
    await expect(messageSwitcher).toContainText("2/2");
  });
});
