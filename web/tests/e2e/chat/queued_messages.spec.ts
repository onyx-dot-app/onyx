import { test, expect, Page, Route } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";

// Send a message and hold the API response so chatState stays non-"input".
// Returns a release function that lets the held response proceed.
async function sendAndHoldResponse(
  page: Page,
  message: string
): Promise<() => void> {
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });

  const routePattern = "**/api/chat/send-chat-message";
  let intercepted = false;

  const handler = async (route: Route) => {
    if (intercepted) {
      await route.continue();
      return;
    }
    intercepted = true;
    await held;
    await route.continue();
  };

  await page.route(routePattern, handler);

  const textarea = page.locator("#onyx-chat-input-textbox");
  await textarea.fill(message);
  await page.locator("#onyx-chat-input-send-button").click();

  // Wait for the submit flow to process (textarea cleared by resetInputBar)
  await expect(textarea).toHaveText("", { timeout: 5000 });

  return () => {
    release();
  };
}

async function queueMessage(page: Page, message: string) {
  const textarea = page.locator("#onyx-chat-input-textbox");
  await textarea.fill(message);
  await textarea.press("Enter");
  await expect(textarea).toHaveText("", { timeout: 2000 });
}

test.describe("Queued Messages", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
  });

  test.afterEach(async ({ page }) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("queues a message during streaming and auto-sends on completion", async ({
    page,
  }) => {
    await sendMessage(page, "Hi, tell me a joke");

    const release = await sendAndHoldResponse(page, "Tell me another joke");

    await queueMessage(page, "And one more please");

    const queueBars = page.locator("[data-testid='queued-message-bar']");
    await expect(queueBars).toHaveCount(1);
    await expect(queueBars.first()).toContainText("And one more please");

    release();

    // Held response completes (2nd AI message), then queued message auto-sends (3rd)
    await expect(page.locator('[data-testid="onyx-ai-message"]')).toHaveCount(
      3,
      { timeout: 30000 }
    );

    await expect(queueBars).toHaveCount(0);
  });

  test("queues multiple messages and sends them in order", async ({ page }) => {
    await sendMessage(page, "Hello");

    const release = await sendAndHoldResponse(page, "Tell me about dogs");

    await queueMessage(page, "First queued");
    await queueMessage(page, "Second queued");
    await queueMessage(page, "Third queued");

    const queueBars = page.locator("[data-testid='queued-message-bar']");
    await expect(queueBars).toHaveCount(3);
    await expect(queueBars.nth(0)).toContainText("First queued");
    await expect(queueBars.nth(1)).toContainText("Second queued");
    await expect(queueBars.nth(2)).toContainText("Third queued");

    release();

    // 1 original + 1 held + 3 queued = 5 AI messages total
    await expect(page.locator('[data-testid="onyx-ai-message"]')).toHaveCount(
      5,
      { timeout: 60000 }
    );
    await expect(queueBars).toHaveCount(0);
  });

  test("discards queued message via trash icon", async ({ page }) => {
    await sendMessage(page, "Hello");

    const release = await sendAndHoldResponse(page, "Tell me about cats");

    await queueMessage(page, "First queued");
    await queueMessage(page, "Second queued");

    const queueBars = page.locator("[data-testid='queued-message-bar']");
    await expect(queueBars).toHaveCount(2);

    // Click trash on the first bar
    await queueBars.nth(0).locator("button").click();

    await expect(queueBars).toHaveCount(1);
    await expect(queueBars.first()).toContainText("Second queued");

    release();

    // 1 original + 1 held + 1 remaining queued = 3 AI messages
    await expect(page.locator('[data-testid="onyx-ai-message"]')).toHaveCount(
      3,
      { timeout: 30000 }
    );
  });

  test("navigates queued messages with arrow keys and edits with Enter", async ({
    page,
  }) => {
    await sendMessage(page, "Hello");

    const release = await sendAndHoldResponse(page, "Second message");

    await queueMessage(page, "First queued");
    await queueMessage(page, "Second queued");

    const textarea = page.locator("#onyx-chat-input-textbox");
    const queueBars = page.locator("[data-testid='queued-message-bar']");

    // Up arrow: highlights last bar
    await textarea.press("ArrowUp");
    await expect(queueBars.nth(1)).toContainText("edit ·");

    // Up again: highlights first bar
    await textarea.press("ArrowUp");
    await expect(queueBars.nth(0)).toContainText("edit ·");
    await expect(queueBars.nth(1)).not.toContainText("edit ·");

    // Down: back to second bar
    await textarea.press("ArrowDown");
    await expect(queueBars.nth(1)).toContainText("edit ·");

    // Enter: move highlighted message into textarea
    await textarea.press("Enter");
    await expect(textarea).toHaveText("Second queued");
    await expect(queueBars).toHaveCount(1);
    await expect(queueBars.first()).toContainText("First queued");

    release();
  });

  test("deletes highlighted message with Backspace", async ({ page }) => {
    await sendMessage(page, "Hello");

    const release = await sendAndHoldResponse(page, "Second message");

    await queueMessage(page, "First queued");
    await queueMessage(page, "Second queued");

    const textarea = page.locator("#onyx-chat-input-textbox");
    const queueBars = page.locator("[data-testid='queued-message-bar']");

    // Highlight last bar and delete it
    await textarea.press("ArrowUp");
    await expect(queueBars.nth(1)).toContainText("edit ·");

    await textarea.press("Backspace");
    await expect(queueBars).toHaveCount(1);
    await expect(queueBars.first()).toContainText("First queued");

    release();
  });

  test("Escape exits navigation mode without modifying queue", async ({
    page,
  }) => {
    await sendMessage(page, "Hello");

    const release = await sendAndHoldResponse(page, "Second message");

    await queueMessage(page, "Queued message");

    const textarea = page.locator("#onyx-chat-input-textbox");
    const queueBars = page.locator("[data-testid='queued-message-bar']");

    // Enter navigation, then escape
    await textarea.press("ArrowUp");
    await expect(queueBars.first()).toContainText("edit ·");

    await textarea.press("Escape");
    await expect(queueBars).toHaveCount(1);
    await expect(queueBars.first()).not.toContainText("edit ·");

    release();
  });

  test("shows queued message placeholder text", async ({ page }) => {
    await sendMessage(page, "Hello");

    const release = await sendAndHoldResponse(page, "Second message");

    await queueMessage(page, "Queued message");

    const textarea = page.locator("#onyx-chat-input-textbox");
    await expect(textarea).toHaveAttribute(
      "data-placeholder",
      "Press up to edit queued messages"
    );

    release();
  });

  test("enforces queue limit of 5 messages", async ({ page }) => {
    await sendMessage(page, "Hello");

    const release = await sendAndHoldResponse(page, "Second message");

    for (let i = 1; i <= 5; i++) {
      await queueMessage(page, `Message ${i}`);
    }

    const queueBars = page.locator("[data-testid='queued-message-bar']");
    await expect(queueBars).toHaveCount(5);

    // 6th message should NOT queue — textarea keeps the text
    const textarea = page.locator("#onyx-chat-input-textbox");
    await textarea.fill("Message 6");
    await textarea.press("Enter");

    await expect(textarea).toHaveText("Message 6");
    await expect(queueBars).toHaveCount(5);

    release();
  });
});
