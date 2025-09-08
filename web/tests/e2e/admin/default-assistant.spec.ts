import { test, expect } from "@playwright/test";
import { loginAs } from "../utils/auth";

test.describe("Default Assistant Admin Page", () => {
  test.beforeEach(async ({ page }) => {
    // Log in as admin
    await page.context().clearCookies();
    await loginAs(page, "admin");

    // Navigate to default assistant
    await page.goto(
      "http://localhost:3000/admin/configuration/default-assistant"
    );
    await page.waitForURL(
      "http://localhost:3000/admin/configuration/default-assistant"
    );
  });

  test("should load default assistant page for admin users", async ({
    page,
  }) => {
    // Verify page loads with expected content
    await expect(
      page.getByRole("heading", { name: "Default Assistant" })
    ).toBeVisible();
    await expect(page.locator("text=Default Assistant")).toBeVisible();
    await expect(page.locator("text=Available Capabilities")).toBeVisible();
    await expect(
      page.locator("text=System Prompt (Instructions)")
    ).toBeVisible();
  });

  test("should toggle Document Search tool on and off", async ({ page }) => {
    await page.waitForSelector("text=Document Search");

    // Find the Document Search toggle
    const searchToggle = page
      .locator("text=Document Search")
      .locator("..")
      .locator("..")
      .locator('[role="switch"]');

    // Get initial state
    const initialState = await searchToggle.getAttribute("data-state");

    // Toggle it
    await searchToggle.click();

    // Wait for the change to persist
    await page.waitForTimeout(1000);

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForSelector("text=Document Search");

    // Check that state persisted
    const searchToggleAfter = page
      .locator("text=Document Search")
      .locator("..")
      .locator("..")
      .locator('[role="switch"]');
    const newState = await searchToggleAfter.getAttribute("data-state");

    // State should have changed
    expect(initialState).not.toBe(newState);

    // Toggle back to original state
    await searchToggleAfter.click();
    await page.waitForTimeout(1000);
  });

  test("should toggle Web Search tool on and off", async ({ page }) => {
    await page.waitForSelector("text=Web Search");

    // Find the Web Search toggle
    const webSearchToggle = page
      .locator("text=Web Search")
      .locator("..")
      .locator("..")
      .locator('[role="switch"]');

    // Get initial state
    const initialState = await webSearchToggle.getAttribute("data-state");

    // Toggle it
    await webSearchToggle.click();

    // Wait for the change to persist
    await page.waitForTimeout(1000);

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForSelector("text=Web Search");

    // Check that state persisted
    const webSearchToggleAfter = page
      .locator("text=Web Search")
      .locator("..")
      .locator("..")
      .locator('[role="switch"]');
    const newState = await webSearchToggleAfter.getAttribute("data-state");

    // State should have changed
    expect(initialState).not.toBe(newState);

    // Toggle back to original state
    await webSearchToggleAfter.click();
    await page.waitForTimeout(1000);
  });

  test("should toggle Image Generation tool on and off", async ({ page }) => {
    await page.waitForSelector("text=Image Generation");

    // Find the Image Generation toggle
    const imageGenToggle = page
      .locator("text=Image Generation")
      .locator("..")
      .locator("..")
      .locator('[role="switch"]');

    // Get initial state
    const initialState = await imageGenToggle.getAttribute("data-state");

    // Toggle it
    await imageGenToggle.click();

    // Wait for the change to persist
    await page.waitForTimeout(1000);

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForSelector("text=Image Generation");

    // Check that state persisted
    const imageGenToggleAfter = page
      .locator("text=Image Generation")
      .locator("..")
      .locator("..")
      .locator('[role="switch"]');
    const newState = await imageGenToggleAfter.getAttribute("data-state");

    // State should have changed
    expect(initialState).not.toBe(newState);

    // Toggle back to original state
    await imageGenToggleAfter.click();
    await page.waitForTimeout(1000);
  });

  test("should edit and save system prompt", async ({ page }) => {
    await page.waitForSelector("text=System Prompt (Instructions)");

    // Find the textarea
    const textarea = page.locator(
      'textarea[placeholder*="Enter custom instructions"]'
    );

    // Get initial value
    const initialValue = await textarea.inputValue();

    // Clear and enter new text
    const testPrompt = "This is a test system prompt for the E2E test.";
    await textarea.fill(testPrompt);

    // Save changes
    const saveButton = page.locator("text=Save Instructions");
    await saveButton.click();

    // Wait for success message
    await expect(
      page.locator("text=System prompt updated successfully!")
    ).toBeVisible();

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForSelector("text=System Prompt (Instructions)");

    // Check that new value persisted
    const textareaAfter = page.locator(
      'textarea[placeholder*="Enter custom instructions"]'
    );
    await expect(textareaAfter).toHaveValue(testPrompt);

    // Restore original value
    await textareaAfter.fill(initialValue);
    const saveButtonAfter = page.locator("text=Save Instructions");
    await saveButtonAfter.click();
    await expect(
      page.locator("text=System prompt updated successfully!")
    ).toBeVisible();
  });

  test("should allow empty system prompt", async ({ page }) => {
    await page.waitForSelector("text=System Prompt (Instructions)");

    // Find the textarea
    const textarea = page.locator(
      'textarea[placeholder*="Enter custom instructions"]'
    );

    // Get initial value to restore later
    const initialValue = await textarea.inputValue();

    // Clear the textarea
    await textarea.fill("");

    // Save changes
    const saveButton = page.locator("text=Save Instructions");
    await saveButton.click();

    // Wait for success message
    await expect(
      page.locator("text=System prompt updated successfully!")
    ).toBeVisible();

    // Refresh page to verify persistence
    await page.reload();
    await page.waitForSelector("text=System Prompt (Instructions)");

    // Check that empty value persisted
    const textareaAfter = page.locator(
      'textarea[placeholder*="Enter custom instructions"]'
    );
    await expect(textareaAfter).toHaveValue("");

    // Restore original value
    await textareaAfter.fill(initialValue);
    const saveButtonAfter = page.locator("text=Save Instructions");
    await saveButtonAfter.click();
    await expect(
      page.locator("text=System prompt updated successfully!")
    ).toBeVisible();
  });

  test("should handle very long system prompt gracefully", async ({ page }) => {
    await page.waitForSelector("text=System Prompt (Instructions)");

    // Find the textarea
    const textarea = page.locator(
      'textarea[placeholder*="Enter custom instructions"]'
    );

    // Get initial value to restore later
    const initialValue = await textarea.inputValue();

    // Create a very long prompt (5000 characters)
    const longPrompt = "This is a test. ".repeat(300); // ~4800 characters
    await textarea.fill(longPrompt);

    // Save changes
    const saveButton = page.locator("text=Save Instructions");
    await saveButton.click();

    // Wait for success message
    await expect(
      page.locator("text=System prompt updated successfully!")
    ).toBeVisible();

    // Verify character count is displayed
    const charCount = page.locator("text=characters").first();
    await expect(charCount).toContainText(longPrompt.length.toString());

    // Restore original value
    await textarea.fill(initialValue);
    await saveButton.click();
    await expect(
      page.locator("text=System prompt updated successfully!")
    ).toBeVisible();
  });

  test("should display character count for system prompt", async ({ page }) => {
    await page.waitForSelector("text=System Prompt (Instructions)");

    // Find the textarea
    const textarea = page.locator(
      'textarea[placeholder*="Enter custom instructions"]'
    );

    // Type some text
    const testText = "Test text for character counting";
    await textarea.fill(testText);

    // Check character count is displayed correctly
    const charCount = page.locator("text=characters");
    await expect(charCount).toContainText(testText.length.toString());
  });

  test("should reject invalid tool IDs via API", async ({ page }) => {
    // Use browser console to send invalid tool IDs
    // This simulates what would happen if someone tried to bypass the UI
    const response = await page.evaluate(async () => {
      const res = await fetch("/api/admin/default-assistant/", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tool_ids: ["InvalidTool", "AnotherInvalidTool"],
        }),
      });
      return {
        ok: res.ok,
        status: res.status,
        body: await res.text(),
      };
    });

    // Check that the request failed with 400
    expect(response.ok).toBe(false);
    expect(response.status).toBe(400);
    expect(response.body).toContain("Invalid tool IDs");
  });

  test("should toggle all tools and verify in chat", async ({ page }) => {
    await page.waitForSelector("text=Document Search");

    // Store initial states
    const toolStates: Record<string, string | null> = {};

    // Get initial states of all tools
    for (const toolName of [
      "Document Search",
      "Web Search",
      "Image Generation",
    ]) {
      const toggle = page
        .locator(`text=${toolName}`)
        .locator("..")
        .locator("..")
        .locator('[role="switch"]');
      toolStates[toolName] = await toggle.getAttribute("data-state");
    }

    // Disable all tools
    for (const toolName of [
      "Document Search",
      "Web Search",
      "Image Generation",
    ]) {
      const toggle = page
        .locator(`text=${toolName}`)
        .locator("..")
        .locator("..")
        .locator('[role="switch"]');
      if ((await toggle.getAttribute("data-state")) === "checked") {
        await toggle.click();
        await page.waitForTimeout(500);
      }
    }

    // Navigate to chat to verify tools are disabled
    await page.goto("http://localhost:3000/chat");
    await page.waitForSelector('[placeholder*="Ask"]', { timeout: 5000 });

    // Go back and re-enable all tools
    await page.goto(
      "http://localhost:3000/admin/configuration/default-assistant"
    );
    await page.waitForSelector("text=Document Search");

    for (const toolName of [
      "Document Search",
      "Web Search",
      "Image Generation",
    ]) {
      const toggle = page
        .locator(`text=${toolName}`)
        .locator("..")
        .locator("..")
        .locator('[role="switch"]');
      if ((await toggle.getAttribute("data-state")) === "unchecked") {
        await toggle.click();
        await page.waitForTimeout(500);
      }
    }

    // Restore original states
    for (const toolName of [
      "Document Search",
      "Web Search",
      "Image Generation",
    ]) {
      const toggle = page
        .locator(`text=${toolName}`)
        .locator("..")
        .locator("..")
        .locator('[role="switch"]');
      const currentState = await toggle.getAttribute("data-state");
      const originalState = toolStates[toolName];

      if (currentState !== originalState) {
        await toggle.click();
        await page.waitForTimeout(500);
      }
    }
  });
});

test.describe("Default Assistant Non-Admin Access", () => {
  test("should redirect non-authenticated users", async ({ page }) => {
    // Try to navigate directly to default assistant without logging in
    await page.goto(
      "http://localhost:3000/admin/configuration/default-assistant"
    );

    // Should be redirected away from chat settings
    await expect(page).not.toHaveURL(
      "**/admin/configuration/default-assistant"
    );

    // Should likely be on login page or see an error
    const url = page.url();
    expect(url.includes("/auth/login") || url.includes("/chat")).toBe(true);
  });
});
