import { test, expect } from "@chromatic-com/playwright";
import type { Page } from "@playwright/test";
import { loginAsRandomUser } from "../utils/auth";
import { sendMessage, startNewChat } from "../utils/chatActions";

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
    (await autoScrollSwitch.getAttribute("data-state")) === "checked";

  if (isCurrentlyChecked !== enabled) {
    await autoScrollSwitch.click();
    // Wait for the switch state to update
    const expectedState = enabled ? "checked" : "unchecked";
    await expect(autoScrollSwitch).toHaveAttribute("data-state", expectedState);
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
