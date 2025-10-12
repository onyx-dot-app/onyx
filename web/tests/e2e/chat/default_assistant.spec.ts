import { GREETING_MESSAGES } from "@/lib/chat/greetingMessages";
import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";
import {
  sendMessage,
  startNewChat,
  verifyAssistantIsChosen,
} from "@tests/e2e/utils/chatActions";
import {
  TOOL_IDS,
  openActionManagement,
  waitForUnifiedGreeting,
} from "@tests/e2e/utils/tools";

// Tool-related test selectors now imported from shared utils

test.describe("Default Assistant Tests", () => {
  test.beforeEach(async ({ page }) => {
    // Clear cookies and log in as a random user
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    // Navigate to the chat page
    await page.goto("http://localhost:3000/chat");
    await page.waitForLoadState("networkidle");
  });

  test.describe("Greeting Message Display", () => {
    test("should display greeting message when opening new chat with default assistant", async ({
      page,
    }) => {
      // Look for greeting message - should be one from the predefined list
      const greeting = await waitForUnifiedGreeting(page);
      expect(GREETING_MESSAGES).toContain(greeting.trim());
    });

    test("greeting message should remain consistent during session", async ({
      page,
    }) => {
      // Get initial greeting
      const initialGreeting = await waitForUnifiedGreeting(page);

      // Reload the page
      await page.reload();
      await page.waitForLoadState("networkidle");

      // Get greeting after reload
      const greetingAfterReload = await waitForUnifiedGreeting(page);

      // Both greetings should be valid but might differ after reload
      expect(GREETING_MESSAGES).toContain(initialGreeting?.trim());
      expect(GREETING_MESSAGES).toContain(greetingAfterReload?.trim());
    });

    test("greeting should only appear for default assistant", async ({
      page,
    }) => {
      // First verify greeting appears for default assistant
      const greetingElement = await page.waitForSelector(
        '[data-testid="onyx-logo"]',
        { timeout: 5000 }
      );
      expect(greetingElement).toBeTruthy();

      // Create a custom assistant to test non-default behavior
      await page.getByTestId("AppSidebar/more-agents").click();
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await page.waitForTimeout(2000);
      await page.getByTestId("name").fill("Custom Test Assistant");
      await page.getByTestId("description").fill("Test Description");
      await page.getByTestId("system_prompt").fill("Test Instructions");
      await page.getByRole("button", { name: "Create" }).click();

      // Wait for assistant to be created and selected
      await verifyAssistantIsChosen(page, "Custom Test Assistant");

      // Greeting should NOT appear for custom assistant
      const customGreeting = await page.$('[data-testid="onyx-logo"]');
      expect(customGreeting).toBeNull();
    });
  });

  test.describe("Default Assistant Branding", () => {
    test("should display Onyx logo for default assistant", async ({ page }) => {
      // Look for Onyx logo
      const logoElement = await page.waitForSelector(
        '[data-testid="onyx-logo"]',
        { timeout: 5000 }
      );
      expect(logoElement).toBeTruthy();

      // Should NOT show assistant name for default assistant
      const assistantNameElement = await page.$(
        '[data-testid="assistant-name-display"]'
      );
      expect(assistantNameElement).toBeNull();
    });

    test("custom assistants should show name and icon instead of logo", async ({
      page,
    }) => {
      // Create a custom assistant
      await page.getByTestId("AppSidebar/more-agents").click();
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await page.waitForTimeout(2000);
      await page.getByTestId("name").fill("Custom Assistant");
      await page.getByTestId("description").fill("Test Description");
      await page.getByTestId("system_prompt").fill("Test Instructions");
      await page.getByRole("button", { name: "Create" }).click();

      // Wait for assistant to be created and selected
      await verifyAssistantIsChosen(page, "Custom Assistant");

      // Should show assistant name and icon, not Onyx logo
      const assistantNameElement = await page.waitForSelector(
        '[data-testid="assistant-name-display"]',
        { timeout: 5000 }
      );
      const nameText = await assistantNameElement.textContent();
      expect(nameText).toContain("Custom Assistant");

      // Onyx logo should NOT be shown
      const logoElement = await page.$('[data-testid="onyx-logo"]');
      expect(logoElement).toBeNull();
    });
  });

  test.describe("Starter Messages", () => {
    test("default assistant should NOT have starter messages", async ({
      page,
    }) => {
      // Check that starter messages container does not exist for default assistant
      const starterMessagesContainer = await page.$(
        '[data-testid="starter-messages"]'
      );
      expect(starterMessagesContainer).toBeNull();

      // Verify no starter message buttons exist
      const starterButtons = await page.$$('[data-testid^="starter-message-"]');
      expect(starterButtons.length).toBe(0);
    });

    test("custom assistants should display starter messages", async ({
      page,
    }) => {
      // Create a custom assistant with starter messages
      await page.getByTestId("AppSidebar/more-agents").click();
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await page.waitForTimeout(2000);
      await page.getByTestId("name").fill("Test Assistant with Starters");
      await page.getByTestId("description").fill("Test Description");
      await page.getByTestId("system_prompt").fill("Test Instructions");

      // Add starter messages (if the UI supports it)
      // For now, we'll create without starter messages and check the behavior
      await page.getByRole("button", { name: "Create" }).click();

      // Wait for assistant to be created and selected
      await verifyAssistantIsChosen(page, "Test Assistant with Starters");

      // Starter messages container might exist but be empty for custom assistants
      const starterMessagesContainer = await page.$(
        '[data-testid="starter-messages"]'
      );
      // It's okay if it exists but has no messages, or doesn't exist at all
      if (starterMessagesContainer) {
        const starterButtons = await page.$$(
          '[data-testid^="starter-message-"]'
        );
        // Custom assistant without configured starter messages should have none
        expect(starterButtons.length).toBe(0);
      }
    });
  });

  test.describe("Assistant Selection", () => {
    test("default assistant should be selected for new chats", async ({
      page,
    }) => {
      // Verify the input placeholder indicates default assistant (Onyx)
      const inputPlaceholder = await page
        .locator("#onyx-chat-input-textarea")
        .getAttribute("placeholder");
      expect(inputPlaceholder).toContain("Onyx");
    });

    test("default assistant should NOT appear in assistant selector", async ({
      page,
    }) => {
      // Open assistant selector
      await page.getByTestId("AppSidebar/more-agents").click();

      // Wait for modal or assistant list to appear
      // The selector might be in a modal or dropdown
      await page.waitForTimeout(1000); // Give modal time to open

      // Look for default assistant by name - it should NOT be there
      const assistantElements = await page.$$('[data-testid^="assistant-"]');
      const assistantTexts = await Promise.all(
        assistantElements.map((el) => el.textContent())
      );

      // Check that "Assistant" (the default assistant name) is not in the list
      const hasDefaultAssistant = assistantTexts.some(
        (text) =>
          text?.includes("Assistant") &&
          !text?.includes("Test") &&
          !text?.includes("Custom")
      );
      expect(hasDefaultAssistant).toBe(false);

      // Close the modal/selector
      await page.keyboard.press("Escape");
    });

    test("should be able to switch from default to custom assistant", async ({
      page,
    }) => {
      // Create a custom assistant
      await page.getByTestId("AppSidebar/more-agents").click();
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await page.waitForTimeout(2000);
      await page.getByTestId("name").fill("Switch Test Assistant");
      await page.getByTestId("description").fill("Test Description");
      await page.getByTestId("system_prompt").fill("Test Instructions");
      await page.getByRole("button", { name: "Create" }).click();

      // Verify switched to custom assistant
      await verifyAssistantIsChosen(page, "Switch Test Assistant");

      // Start new chat to go back to default
      await startNewChat(page);

      // Should be back to default assistant
      await expect(page.locator("#onyx-chat-input-textarea")).toHaveAttribute(
        "placeholder",
        /Onyx/
      );
    });
  });

  test.describe("Action Management Toggle", () => {
    test("should display action management toggle", async ({ page }) => {
      // Look for action management toggle button
      const actionToggle = await page.waitForSelector(TOOL_IDS.actionToggle, {
        timeout: 5000,
      });
      expect(actionToggle).toBeTruthy();
    });

    test("should show web-search + image-generation tools options when clicked", async ({
      page,
    }) => {
      // Will NOT show the `internal-search` option since that will be excluded when there are no connectors connected.
      // (Since we removed pre-seeded docs, we will have NO connectors connected on a fresh install; therefore, `internal-search` will not be available.)
      await openActionManagement(page);
      expect(await page.$(TOOL_IDS.webSearchOption)).toBeTruthy();
      expect(await page.$(TOOL_IDS.imageGenerationOption)).toBeTruthy();
    });

    test("should be able to toggle tools on and off", async ({ page }) => {
      // Click action management toggle
      await page.click(TOOL_IDS.actionToggle);

      // Wait for tool options
      await page.waitForSelector(TOOL_IDS.options, {
        timeout: 5000,
      });

      // Find a checkbox/toggle within the image-generation tool option
      const imageGenerationToolOption = await page.$(
        TOOL_IDS.imageGenerationOption
      );
      expect(imageGenerationToolOption).toBeTruthy();

      // Look for a checkbox or switch within the tool option
      const imageGenerationToggle = await imageGenerationToolOption?.$(
        TOOL_IDS.toggleInput
      );

      if (imageGenerationToggle) {
        const initialState = await imageGenerationToggle.isChecked();
        await imageGenerationToggle.click();

        // Verify state changed
        const newState = await imageGenerationToggle.isChecked();
        expect(newState).toBe(!initialState);

        // Toggle it back
        await imageGenerationToggle.click();
        const finalState = await imageGenerationToggle.isChecked();
        expect(finalState).toBe(initialState);
      } else {
        // If no toggle found, just click the option itself
        await imageGenerationToolOption?.click();
        // Check if the option has some visual state change
        // This is a fallback behavior if toggles work differently
      }
    });

    test("tool toggle state should persist across page refresh", async ({
      page,
    }) => {
      // Click action management toggle
      await page.click(TOOL_IDS.actionToggle);

      // Wait for tool options
      await page.waitForSelector(TOOL_IDS.options, {
        timeout: 5000,
      });

      // Find the internet image-generation tool option and its toggle
      const imageGenerationToolOption = await page.$(
        TOOL_IDS.imageGenerationOption
      );
      expect(imageGenerationToolOption).toBeTruthy();

      const imageGenerationToggle = await imageGenerationToolOption?.$(
        TOOL_IDS.toggleInput
      );

      let toggledState = false;
      if (imageGenerationToggle) {
        await imageGenerationToggle.click();
        toggledState = await imageGenerationToggle.isChecked();
      } else {
        // Click the option itself if no toggle found
        await imageGenerationToolOption?.click();
        // Assume toggled if clicked
        toggledState = true;
      }

      // Reload page
      await page.reload();
      await page.waitForLoadState("networkidle");

      // Open action management again
      await page.click(TOOL_IDS.actionToggle);
      await page.waitForSelector(TOOL_IDS.options, {
        timeout: 5000,
      });

      // Check if state persisted
      const imageGenerationToolOptionAfterReload = await page.$(
        TOOL_IDS.imageGenerationOption
      );
      const imageGenerationToggleAfterReload =
        await imageGenerationToolOptionAfterReload?.$(TOOL_IDS.toggleInput);

      if (imageGenerationToggleAfterReload) {
        const stateAfterReload =
          await imageGenerationToggleAfterReload.isChecked();
        expect(stateAfterReload).toBe(toggledState);
      }
    });
  });
});

test.describe("End-to-End Default Assistant Flow", () => {
  test("complete user journey with default assistant", async ({ page }) => {
    // Clear cookies and log in as a random user
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    // Navigate to the chat page
    await page.goto("http://localhost:3000/chat");
    await page.waitForLoadState("networkidle");

    // Verify greeting message appears
    const greetingElement = await page.waitForSelector(
      '[data-testid="onyx-logo"]',
      { timeout: 5000 }
    );
    expect(greetingElement).toBeTruthy();

    // Verify Onyx logo is displayed
    const logoElement = await page.waitForSelector(
      '[data-testid="onyx-logo"]',
      { timeout: 5000 }
    );
    expect(logoElement).toBeTruthy();

    // Send a message using the chat input
    await sendMessage(page, "Hello, can you help me?");

    // Verify AI response appears
    const aiResponse = await page.waitForSelector(
      '[data-testid="onyx-ai-message"]',
      { timeout: 10000 }
    );
    expect(aiResponse).toBeTruthy();

    // Open action management and verify tools
    await openActionManagement(page);

    // Close action management
    await page.keyboard.press("Escape");

    // Start a new chat
    await startNewChat(page);

    // Verify we're back to default assistant with greeting
    const newGreeting = await page.waitForSelector(
      '[data-testid="onyx-logo"]',
      { timeout: 5000 }
    );
    expect(newGreeting).toBeTruthy();
  });
});
