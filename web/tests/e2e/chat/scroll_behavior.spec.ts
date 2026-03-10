import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";
import { sendMessage, startNewChat } from "@tests/e2e/utils/chatActions";

/**
 * Helper to toggle auto-scroll setting via the settings panel
 */
async function setAutoScroll(page: Page, enabled: boolean) {
  // Open user dropdown menu (same pattern as other tests)
  await page.locator("#onyx-user-dropdown").click();
  await page.getByText("User Settings").first().click();
  // Wait for dialog to appear
  await page.waitForSelector('[role="dialog"]', { state: "visible" });

  // Navigate to Chat Preferences tab
  await page
    .locator('a[href="/app/settings/chat-preferences"]')
    .click({ force: true });

  // Find the auto-scroll switch by locating the label text and then finding
  // the switch within the same container
  const autoScrollSwitch = page
    .locator("label")
    .filter({ hasText: "Chat Auto-scroll" })
    .locator('button[role="switch"]');

  await autoScrollSwitch.waitFor({ state: "visible" });

  const isCurrentlyChecked =
    (await autoScrollSwitch.getAttribute("aria-checked")) === "true";

  if (isCurrentlyChecked !== enabled) {
    await autoScrollSwitch.click();
    // Wait for the switch state to update
    const expectedState = enabled ? "true" : "false";
    await expect(autoScrollSwitch).toHaveAttribute(
      "aria-checked",
      expectedState
    );
  }

  await page.locator('a[href="/app"]').click({ force: true });
}

/**
 * Helper to get the scroll container element
 */
function getScrollContainer(page: Page) {
  // The scroll container is the div with overflow-y-auto inside ChatUI
  return page.locator(".overflow-y-auto").first();
}

test.describe("Chat Scroll Behavior", () => {
  // Configure this suite to run serially to resepect auto-scroll settings
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAsRandomUser(page);
    await page.goto("/app");
    const nameInput = page.getByPlaceholder("Your name");
    await nameInput.waitFor();
    await nameInput.fill("Playwright Tester");
    await page.getByText("Save").click();
    await Promise.all([
      // Wait for sidebar navigation to be visible to indicate page is loaded
      page.getByText("Agents").first().waitFor(),
      page.getByText("Projects").first().waitFor(),
    ]);
  });

  // TODO(Nik): https://linear.app/onyx-app/issue/ENG-3422/playwright-tests-for-scroll-behavior
  test.skip("Opening existing conversation positions correctly", async ({
    page,
  }) => {
    // Turn off auto-scroll
    await setAutoScroll(page, false);

    // Create a conversation with multiple messages
    await sendMessage(
      page,
      "Message 1: Creating some content to enable scrolling"
    );
    await sendMessage(page, "Message 2: More content for the scroll test");

    // Reload page to simulate opening an existing conversation
    await page.reload();
    await Promise.all([
      // Wait for sidebar navigation to be visible to indicate page is loaded
      page.getByText("Agents").first().waitFor(),
      page.getByText("Projects").first().waitFor(),
    ]);

    // Wait for scroll positioning to complete (content becomes visible)
    await page
      .locator('[data-scroll-ready="true"]')
      .waitFor({ timeout: 30000 });

    // Wait for the user messages to be visible
    const lastUserMessage = page.locator("#onyx-human-message").last();
    await lastUserMessage.waitFor({ state: "visible", timeout: 30000 });

    // Verify the last user message is positioned near the top of the viewport
    const isPositionedCorrectly = await lastUserMessage.evaluate(
      (el: HTMLElement) => {
        const scrollContainer = el.closest(".overflow-y-auto");
        if (!scrollContainer) return false;

        const containerRect = scrollContainer.getBoundingClientRect();
        const elementRect = el.getBoundingClientRect();

        // Check if element is near the top of the container (within 100px)
        return elementRect.top - containerRect.top < 100;
      }
    );

    expect(isPositionedCorrectly).toBe(true);
  });

  test("Auto-scroll ON: scrolls to bottom on new message", async ({ page }) => {
    // Ensure auto-scroll is ON (default)
    await setAutoScroll(page, true);

    // Send a message
    await sendMessage(page, "Hello, this is a test message");

    // Send another message to create some content
    await sendMessage(page, "Another message to test scrolling behavior");

    // The scroll container should be scrolled to bottom
    const scrollContainer = getScrollContainer(page);
    const isAtBottom = await scrollContainer.evaluate((el: HTMLElement) => {
      return Math.abs(el.scrollHeight - el.scrollTop - el.clientHeight) < 10;
    });

    expect(isAtBottom).toBe(true);
  });
});

/**
 * Tests for the Dynamic Bottom Spacer feature.
 *
 * The DynamicBottomSpacer creates a "fresh chat" effect where new messages
 * appear at the top of the viewport (below the header), giving each exchange
 * a clean slate appearance while preserving scroll-up access to history.
 */
test.describe("Dynamic Bottom Spacer - Fresh Chat Effect", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAsRandomUser(page);
    await page.goto("/app");
    const nameInput = page.getByPlaceholder("Your name");
    await nameInput.waitFor();
    await nameInput.fill("Playwright Tester");
    await page.getByText("Save").click();
    await Promise.all([
      page.getByText("Agents").first().waitFor(),
      page.getByText("Projects").first().waitFor(),
    ]);
  });

  /**
   * Helper to get the position of an element relative to scroll container
   */
  async function getElementPositionInContainer(
    page: Page,
    elementLocator: ReturnType<Page["locator"]>
  ) {
    return elementLocator.evaluate((el: HTMLElement) => {
      const scrollContainer = el.closest(".overflow-y-auto");
      if (!scrollContainer) return null;

      const containerRect = scrollContainer.getBoundingClientRect();
      const elementRect = el.getBoundingClientRect();

      return {
        topOffset: elementRect.top - containerRect.top,
        containerHeight: containerRect.height,
        elementTop: elementRect.top,
        containerTop: containerRect.top,
      };
    });
  }

  test("Follow-up message appears near top of viewport (fresh chat effect)", async ({
    page,
  }) => {
    // First, create some conversation history
    await sendMessage(
      page,
      "This is the first message to establish conversation history"
    );

    // Send a follow-up message - this should trigger the fresh chat effect
    await sendMessage(
      page,
      "This follow-up message should appear near the top of the viewport"
    );

    // Get the last user message (the follow-up)
    const lastUserMessage = page.locator("#onyx-human-message").last();
    await lastUserMessage.waitFor({ state: "visible" });

    // Check that the follow-up message is positioned near the top of the container
    // (within ~150px to account for sticky header and some padding)
    await expect
      .poll(
        async () => {
          const position = await getElementPositionInContainer(
            page,
            lastUserMessage
          );
          return position?.topOffset ?? Number.POSITIVE_INFINITY;
        },
        { timeout: 5000 }
      )
      .toBeLessThan(150);
  });

  test("Dynamic spacer element exists and has correct attributes", async ({
    page,
  }) => {
    // Send a message to start a conversation
    await sendMessage(page, "Test message to initialize chat");

    // Send a follow-up to trigger the spacer
    await sendMessage(page, "Follow-up message");

    // Verify the dynamic spacer element exists with correct attributes
    const spacer = page.locator('[data-dynamic-spacer="true"]');
    await expect(spacer).toBeVisible({ timeout: 10000 });
    await expect(spacer).toHaveAttribute("aria-hidden", "true");
  });

  test("User can scroll up to see previous messages after fresh chat effect", async ({
    page,
  }) => {
    // Create conversation history
    await sendMessage(page, "First message in the conversation");
    await sendMessage(page, "Second message in the conversation");

    // Send a follow-up (triggers fresh chat effect)
    await sendMessage(page, "Third message - should be at top");

    // Now scroll up to verify previous messages are accessible
    const scrollContainer = getScrollContainer(page);
    await scrollContainer.evaluate((el: HTMLElement) => {
      el.scrollTo({ top: 0, behavior: "instant" });
    });

    // Wait for scroll to complete
    await expect
      .poll(() => scrollContainer.evaluate((el: HTMLElement) => el.scrollTop), {
        timeout: 5000,
      })
      .toBeLessThanOrEqual(1);

    // Verify the first message is now visible
    const firstUserMessage = page.locator("#onyx-human-message").first();
    await expect(firstUserMessage).toBeVisible();

    // Verify the first message content
    await expect(firstUserMessage).toContainText("First message");
  });

  test("Scroll container remains at bottom after AI response completes", async ({
    page,
  }) => {
    // Send a message
    await sendMessage(page, "Please respond with a short message");

    // After AI response completes, verify we're still at the bottom
    const scrollContainer = getScrollContainer(page);
    const isAtBottom = await scrollContainer.evaluate((el: HTMLElement) => {
      // Allow a small tolerance (10px) for rounding
      return Math.abs(el.scrollHeight - el.scrollTop - el.clientHeight) < 10;
    });

    expect(isAtBottom).toBe(true);
  });
});
