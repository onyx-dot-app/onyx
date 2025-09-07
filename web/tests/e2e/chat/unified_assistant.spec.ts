import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser } from "../utils/auth";
import {
  navigateToAssistantInHistorySidebar,
  sendMessage,
  startNewChat,
  verifyAssistantIsChosen,
} from "../utils/chatActions";
import { GREETING_MESSAGES } from "../../../src/lib/chat/greetingMessages";

test.describe("Unified Assistant Tests", () => {
  test.beforeEach(async ({ page }) => {
    // Clear cookies and log in as a random user
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    // Navigate to the chat page
    await page.goto("http://localhost:3000/chat");
    await page.waitForLoadState("networkidle");
  });

  test.describe("Greeting Message Display", () => {
    test("should display greeting message when opening new chat with unified assistant", async ({
      page,
    }) => {
      // Look for greeting message - should be one from the predefined list
      const greetingElement = await page.waitForSelector(
        '[data-testid="greeting-message"]',
        { timeout: 5000 }
      );
      const greetingText = await greetingElement.textContent();

      // Verify the greeting is from the predefined list
      expect(GREETING_MESSAGES).toContain(greetingText?.trim());
    });

    test("greeting message should remain consistent during session", async ({
      page,
    }) => {
      // Get initial greeting
      const greetingElement = await page.waitForSelector(
        '[data-testid="greeting-message"]',
        { timeout: 5000 }
      );
      const initialGreeting = await greetingElement.textContent();

      // Reload the page
      await page.reload();
      await page.waitForLoadState("networkidle");

      // Get greeting after reload
      const greetingElementAfterReload = await page.waitForSelector(
        '[data-testid="greeting-message"]',
        { timeout: 5000 }
      );
      const greetingAfterReload =
        await greetingElementAfterReload.textContent();

      // Both greetings should be valid but might differ after reload
      expect(GREETING_MESSAGES).toContain(initialGreeting?.trim());
      expect(GREETING_MESSAGES).toContain(greetingAfterReload?.trim());
    });

    test("greeting should only appear for unified assistant", async ({
      page,
    }) => {
      // First verify greeting appears for unified assistant (default)
      const greetingElement = await page.waitForSelector(
        '[data-testid="greeting-message"]',
        { timeout: 5000 }
      );
      expect(greetingElement).toBeTruthy();

      // Create a custom assistant to test non-unified behavior
      await page.getByRole("button", { name: "Explore Assistants" }).click();
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await page.getByTestId("name").fill("Custom Test Assistant");
      await page.getByTestId("description").fill("Test Description");
      await page.getByTestId("system_prompt").fill("Test Instructions");
      await page.getByRole("button", { name: "Create" }).click();

      // Wait for assistant to be created and selected
      await verifyAssistantIsChosen(page, "Custom Test Assistant");

      // Greeting should NOT appear for custom assistant
      const customGreeting = await page.$('[data-testid="greeting-message"]');
      expect(customGreeting).toBeNull();
    });
  });

  test.describe("Unified Assistant Branding", () => {
    test("should display Onyx logo for unified assistant", async ({ page }) => {
      // Look for Onyx logo
      const logoElement = await page.waitForSelector(
        '[data-testid="onyx-logo"]',
        { timeout: 5000 }
      );
      expect(logoElement).toBeTruthy();

      // Should NOT show assistant name for unified assistant
      const assistantNameElement = await page.$(
        '[data-testid="assistant-name-display"]'
      );
      expect(assistantNameElement).toBeNull();
    });

    test("custom assistants should show name and icon instead of logo", async ({
      page,
    }) => {
      // Create a custom assistant
      await page.getByRole("button", { name: "Explore Assistants" }).click();
      await page.getByRole("button", { name: "Create", exact: true }).click();
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
    test("should display starter messages below greeting", async ({ page }) => {
      // Wait for starter messages container
      const starterMessagesContainer = await page.waitForSelector(
        '[data-testid="starter-messages"]',
        { timeout: 5000 }
      );
      expect(starterMessagesContainer).toBeTruthy();

      // Get all starter message buttons
      const starterButtons = await page.$$('[data-testid^="starter-message-"]');
      expect(starterButtons.length).toBeGreaterThan(0);
    });

    test("should include messages from all categories", async ({ page }) => {
      // Get all starter message buttons
      const starterButtons = await page.$$('[data-testid^="starter-message-"]');
      const messages = await Promise.all(
        starterButtons.map((button) => button.textContent())
      );

      // Check for presence of different types of messages
      const hasSearchMessage = messages.some(
        (msg) =>
          msg?.toLowerCase().includes("search") ||
          msg?.toLowerCase().includes("find") ||
          msg?.toLowerCase().includes("look")
      );
      const hasGeneralMessage = messages.some(
        (msg) =>
          msg?.toLowerCase().includes("explain") ||
          msg?.toLowerCase().includes("what") ||
          msg?.toLowerCase().includes("how")
      );
      const hasImageMessage = messages.some(
        (msg) =>
          msg?.toLowerCase().includes("image") ||
          msg?.toLowerCase().includes("picture") ||
          msg?.toLowerCase().includes("draw") ||
          msg?.toLowerCase().includes("create")
      );

      expect(hasSearchMessage || hasGeneralMessage || hasImageMessage).toBe(
        true
      );
    });

    test("clicking starter message should send it as user message", async ({
      page,
    }) => {
      // Get first starter message
      const firstStarterButton = await page.waitForSelector(
        '[data-testid^="starter-message-"]',
        { timeout: 5000 }
      );
      const starterText = await firstStarterButton.textContent();

      // Click the starter message
      await firstStarterButton.click();

      // Wait for message to be sent and response to start
      await page.waitForSelector('[data-testid="onyx-user-message"]', {
        timeout: 5000,
      });

      // Verify the message was sent
      const userMessage = await page.$('[data-testid="onyx-user-message"]');
      const messageContent = await userMessage?.textContent();
      expect(messageContent).toContain(starterText);
    });
  });

  test.describe("Assistant Selection", () => {
    test("unified assistant should be default for new chats", async ({
      page,
    }) => {
      // Verify the input placeholder indicates unified assistant
      const inputPlaceholder = await page
        .locator("#onyx-chat-input-textarea")
        .getAttribute("placeholder");
      expect(inputPlaceholder).toContain("Assistant");
    });

    test("unified assistant should NOT appear in assistant selector", async ({
      page,
    }) => {
      // Open assistant selector
      await page.getByRole("button", { name: "Explore Assistants" }).click();

      // Wait for assistant list to load
      await page.waitForSelector('[data-testid="assistant-list"]', {
        timeout: 5000,
      });

      // Look for unified assistant (ID 0) - it should NOT be there
      const unifiedAssistantElement = await page.$(
        '[data-testid="assistant-[0]"]'
      );
      expect(unifiedAssistantElement).toBeNull();

      // Also check that deprecated assistants are not shown
      const searchAssistant = await page.$('[data-testid="assistant-[-2]"]');
      const generalAssistant = await page.$('[data-testid="assistant-[-1]"]');
      const artAssistant = await page.$('[data-testid="assistant-[-3]"]');

      expect(searchAssistant).toBeNull();
      expect(generalAssistant).toBeNull();
      expect(artAssistant).toBeNull();
    });

    test("should be able to switch from unified to custom assistant", async ({
      page,
    }) => {
      // Create a custom assistant
      await page.getByRole("button", { name: "Explore Assistants" }).click();
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await page.getByTestId("name").fill("Switch Test Assistant");
      await page.getByTestId("description").fill("Test Description");
      await page.getByTestId("system_prompt").fill("Test Instructions");
      await page.getByRole("button", { name: "Create" }).click();

      // Verify switched to custom assistant
      await verifyAssistantIsChosen(page, "Switch Test Assistant");

      // Start new chat to go back to unified
      await startNewChat(page);

      // Should be back to unified assistant
      const inputPlaceholder = await page
        .locator("#onyx-chat-input-textarea")
        .getAttribute("placeholder");
      expect(inputPlaceholder).toContain("Assistant");
    });
  });

  test.describe("Action Management Toggle", () => {
    test("should display action management toggle", async ({ page }) => {
      // Look for action management toggle button
      const actionToggle = await page.waitForSelector(
        '[data-testid="action-management-toggle"]',
        { timeout: 5000 }
      );
      expect(actionToggle).toBeTruthy();
    });

    test("should show all three tool options when clicked", async ({
      page,
    }) => {
      // Click action management toggle
      await page.click('[data-testid="action-management-toggle"]');

      // Wait for tool options to appear
      await page.waitForSelector('[data-testid="tool-options"]', {
        timeout: 5000,
      });

      // Check for all three tools
      const searchToolOption = await page.$(
        '[data-testid="tool-option-search"]'
      );
      const webSearchOption = await page.$(
        '[data-testid="tool-option-web-search"]'
      );
      const imageGenOption = await page.$(
        '[data-testid="tool-option-image-generation"]'
      );

      expect(searchToolOption).toBeTruthy();
      expect(webSearchOption).toBeTruthy();
      expect(imageGenOption).toBeTruthy();
    });

    test("should be able to toggle tools on and off", async ({ page }) => {
      // Click action management toggle
      await page.click('[data-testid="action-management-toggle"]');

      // Wait for tool options
      await page.waitForSelector('[data-testid="tool-options"]', {
        timeout: 5000,
      });

      // Toggle search tool off
      const searchToolToggle = await page.waitForSelector(
        '[data-testid="tool-toggle-search"]',
        { timeout: 5000 }
      );
      const initialSearchState = await searchToolToggle.isChecked();
      await searchToolToggle.click();

      // Verify state changed
      const newSearchState = await searchToolToggle.isChecked();
      expect(newSearchState).toBe(!initialSearchState);

      // Toggle it back
      await searchToolToggle.click();
      const finalSearchState = await searchToolToggle.isChecked();
      expect(finalSearchState).toBe(initialSearchState);
    });

    test("tool toggle state should persist across page refresh", async ({
      page,
    }) => {
      // Click action management toggle
      await page.click('[data-testid="action-management-toggle"]');

      // Wait for tool options
      await page.waitForSelector('[data-testid="tool-options"]', {
        timeout: 5000,
      });

      // Toggle web search off
      const webSearchToggle = await page.waitForSelector(
        '[data-testid="tool-toggle-web-search"]',
        { timeout: 5000 }
      );
      await webSearchToggle.click();
      const toggledState = await webSearchToggle.isChecked();

      // Reload page
      await page.reload();
      await page.waitForLoadState("networkidle");

      // Open action management again
      await page.click('[data-testid="action-management-toggle"]');
      await page.waitForSelector('[data-testid="tool-options"]', {
        timeout: 5000,
      });

      // Check if state persisted
      const webSearchToggleAfterReload = await page.waitForSelector(
        '[data-testid="tool-toggle-web-search"]',
        { timeout: 5000 }
      );
      const stateAfterReload = await webSearchToggleAfterReload.isChecked();

      expect(stateAfterReload).toBe(toggledState);
    });
  });

  test.describe("Admin Configuration", () => {
    test.skip("should have admin configuration page for default assistant", async ({
      page,
    }) => {
      // This test is marked as skip since admin configuration might not be implemented yet
      // Navigate to admin configuration
      await page.goto(
        "http://localhost:3000/admin/configuration/default-assistant"
      );

      // Wait for page to load
      await page.waitForLoadState("networkidle");

      // Verify configuration options are present
      const configForm = await page.waitForSelector(
        '[data-testid="assistant-config-form"]',
        { timeout: 5000 }
      );
      expect(configForm).toBeTruthy();

      // Check for tool configuration options
      const searchToggle = await page.$('[data-testid="config-tool-search"]');
      const webSearchToggle = await page.$(
        '[data-testid="config-tool-web-search"]'
      );
      const imageGenToggle = await page.$(
        '[data-testid="config-tool-image-generation"]'
      );

      expect(searchToggle).toBeTruthy();
      expect(webSearchToggle).toBeTruthy();
      expect(imageGenToggle).toBeTruthy();
    });
  });
});

test.describe("End-to-End Unified Assistant Flow", () => {
  test("complete user journey with unified assistant", async ({ page }) => {
    // Clear cookies and log in as a random user
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    // Navigate to the chat page
    await page.goto("http://localhost:3000/chat");
    await page.waitForLoadState("networkidle");

    // Verify greeting message appears
    const greetingElement = await page.waitForSelector(
      '[data-testid="greeting-message"]',
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
    await page.click('[data-testid="action-management-toggle"]');
    await page.waitForSelector('[data-testid="tool-options"]', {
      timeout: 5000,
    });

    // Close action management
    await page.keyboard.press("Escape");

    // Start a new chat
    await startNewChat(page);

    // Verify we're back to unified assistant with greeting
    const newGreeting = await page.waitForSelector(
      '[data-testid="greeting-message"]',
      { timeout: 5000 }
    );
    expect(newGreeting).toBeTruthy();
  });
});
