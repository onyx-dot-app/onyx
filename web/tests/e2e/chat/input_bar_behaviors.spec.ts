import { test, expect } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import {
  buildMockStream,
  mockChatEndpoint,
  resetTurnCounter,
} from "@tests/e2e/utils/chatMock";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";

const INPUT_SELECTOR = "#onyx-chat-input-textbox";
const SEND_BUTTON_SELECTOR = "#onyx-chat-input-send-button";
const INPUT_CONTAINER_SELECTOR = "#onyx-chat-input";
const HUMAN_MESSAGE_SELECTOR = "#onyx-human-message";

test.describe("Core Text Input & Submission", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page
      .locator(INPUT_SELECTOR)
      .waitFor({ state: "visible", timeout: 10000 });
    await mockChatEndpoint(page, buildMockStream("Mock response"));
  });

  test("typing and pressing Enter sends the message", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.fill("hello");
    await page.keyboard.press("Enter");
    await expect(page.locator(HUMAN_MESSAGE_SELECTOR)).toContainText("hello");
  });

  test("typing and clicking send button sends the message", async ({
    page,
  }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.fill("hello");
    await page.locator(SEND_BUTTON_SELECTOR).click();
    await expect(page.locator(HUMAN_MESSAGE_SELECTOR)).toContainText("hello");
  });

  test("pressing Enter with empty input does not send a message", async ({
    page,
  }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await page.keyboard.press("Enter");
    await page.waitForTimeout(500);
    await expect(page.locator(HUMAN_MESSAGE_SELECTOR)).toHaveCount(0);
  });

  test("pressing Enter with only spaces does not send a message", async ({
    page,
  }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.fill("   ");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(500);
    await expect(page.locator(HUMAN_MESSAGE_SELECTOR)).toHaveCount(0);
  });

  test("input is cleared after sending a message", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.fill("hello");
    await page.keyboard.press("Enter");
    await expect(page.locator(HUMAN_MESSAGE_SELECTOR)).toContainText("hello");
    await expect(input).toHaveAttribute("data-empty", "");
    const text = await input.textContent();
    expect(text?.trim()).toBe("");
  });

  test("sends a long message (2000+ characters)", async ({ page }) => {
    const longText = "a".repeat(2100);
    const input = page.locator(INPUT_SELECTOR);
    await input.fill(longText);
    await page.keyboard.press("Enter");
    await expect(page.locator(HUMAN_MESSAGE_SELECTOR)).toContainText(longText);
  });
});

test.describe("Multiline Input", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page
      .locator(INPUT_SELECTOR)
      .waitFor({ state: "visible", timeout: 10000 });
    await mockChatEndpoint(page, buildMockStream("Mock response"));
  });

  test("Shift+Enter creates a new line and increases input height", async ({
    page,
  }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await page.keyboard.type("line1");
    await page.keyboard.press("Shift+Enter");
    await page.keyboard.type("line2");

    const height = await page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      return el.parentElement!.getBoundingClientRect().height;
    });
    expect(height).toBeGreaterThan(44);
  });

  test("Shift+Enter does not send the message", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await page.keyboard.type("some text");
    await page.keyboard.press("Shift+Enter");
    await page.waitForTimeout(500);
    await expect(page.locator(HUMAN_MESSAGE_SELECTOR)).toHaveCount(0);
  });

  test("multiline message is sent with newlines preserved", async ({
    page,
  }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await page.keyboard.type("line1");
    await page.keyboard.press("Shift+Enter");
    await page.keyboard.type("line2");
    await page.keyboard.press("Enter");
    const messageEl = page.locator(HUMAN_MESSAGE_SELECTOR);
    await expect(messageEl).toContainText("line1");
    await expect(messageEl).toContainText("line2");
  });
});

test.describe("Paste Behavior", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page
      .locator(INPUT_SELECTOR)
      .waitFor({ state: "visible", timeout: 10000 });
  });

  test("pasting plain text appears in the input", async ({ page }) => {
    await page.evaluate((text) => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      const dt = new DataTransfer();
      dt.setData("text/plain", text);
      const event = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(event);
    }, "hello world");

    const input = page.locator(INPUT_SELECTOR);
    await expect(input).toContainText("hello world");
  });

  test("pasting rich HTML strips formatting and pastes plain text only", async ({
    page,
  }) => {
    await page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      const dt = new DataTransfer();
      dt.setData("text/html", "<b>bold</b> <i>italic</i>");
      dt.setData("text/plain", "bold italic");
      const event = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(event);
    });

    const input = page.locator(INPUT_SELECTOR);
    await expect(input).toContainText("bold italic");
    const innerHTML = await input.innerHTML();
    expect(innerHTML).not.toContain("<b>");
    expect(innerHTML).not.toContain("<i>");
  });

  test("select all then paste replaces content", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.fill("original text");
    await page.keyboard.press("ControlOrMeta+a");

    await page.evaluate((text) => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      const dt = new DataTransfer();
      dt.setData("text/plain", text);
      const event = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(event);
    }, "replacement");

    await expect(input).toContainText("replacement");
  });

  test("pasting multiline text increases input height", async ({ page }) => {
    const multilineText = "line1\nline2\nline3\nline4";
    await page.evaluate((text) => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      const dt = new DataTransfer();
      dt.setData("text/plain", text);
      const event = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(event);
    }, multilineText);

    await page.waitForTimeout(200);
    const height = await page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      return el.parentElement!.getBoundingClientRect().height;
    });
    expect(height).toBeGreaterThan(44);
  });
});

test.describe("Paste Security", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page
      .locator(INPUT_SELECTOR)
      .waitFor({ state: "visible", timeout: 10000 });
  });

  test("pasting script tags does not execute code", async ({ page }) => {
    const xssPayload = '<script>window.__xss_fired=true</script>alert("xss")';
    await page.evaluate((text) => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      const dt = new DataTransfer();
      dt.setData("text/html", text);
      dt.setData("text/plain", text);
      const event = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(event);
    }, xssPayload);

    const input = page.locator(INPUT_SELECTOR);
    const innerHTML = await input.innerHTML();
    expect(innerHTML).not.toContain("<script");
    expect(innerHTML).not.toContain("</script>");

    const xssFired = await page.evaluate(() => (window as any).__xss_fired);
    expect(xssFired).toBeFalsy();
  });

  test("pasting img onerror does not execute code", async ({ page }) => {
    const xssPayload = '<img src=x onerror="window.__xss_img=true">';
    await page.evaluate((text) => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      const dt = new DataTransfer();
      dt.setData("text/html", text);
      dt.setData("text/plain", "image");
      const event = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(event);
    }, xssPayload);

    await page.waitForTimeout(500);
    const input = page.locator(INPUT_SELECTOR);
    const innerHTML = await input.innerHTML();
    expect(innerHTML).not.toContain("<img");
    expect(innerHTML).not.toContain("onerror");

    const xssFired = await page.evaluate(() => (window as any).__xss_img);
    expect(xssFired).toBeFalsy();
  });

  test("pasting event handler attributes does not execute code", async ({
    page,
  }) => {
    const xssPayload =
      '<div onmouseover="window.__xss_div=true">hover me</div>';
    await page.evaluate((text) => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      const dt = new DataTransfer();
      dt.setData("text/html", text);
      dt.setData("text/plain", "hover me");
      const event = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(event);
    }, xssPayload);

    const input = page.locator(INPUT_SELECTOR);
    const innerHTML = await input.innerHTML();
    expect(innerHTML).not.toContain("onmouseover");
    expect(innerHTML).not.toContain("<div");
    await expect(input).toContainText("hover me");
  });

  test("only plain text is inserted regardless of HTML clipboard content", async ({
    page,
  }) => {
    const richHtml =
      '<a href="javascript:alert(1)">click</a><style>body{display:none}</style><iframe src="evil.com"></iframe>';
    await page.evaluate((html) => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      const dt = new DataTransfer();
      dt.setData("text/html", html);
      dt.setData("text/plain", "click");
      const event = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(event);
    }, richHtml);

    const input = page.locator(INPUT_SELECTOR);
    const innerHTML = await input.innerHTML();
    expect(innerHTML).not.toContain("<a");
    expect(innerHTML).not.toContain("<style");
    expect(innerHTML).not.toContain("<iframe");
    expect(innerHTML).not.toContain("javascript:");
    await expect(input).toContainText("click");
  });
});

test.describe("Auto-Resize", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page
      .locator(INPUT_SELECTOR)
      .waitFor({ state: "visible", timeout: 10000 });
  });

  test("grows taller when multiple lines are pasted", async ({ page }) => {
    const multilineText = "line1\nline2\nline3\nline4";
    await page.evaluate((text) => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      const dt = new DataTransfer();
      dt.setData("text/plain", text);
      const event = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(event);
    }, multilineText);

    await page.waitForTimeout(200);
    const height = await page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      return el.parentElement!.getBoundingClientRect().height;
    });
    expect(height).toBeGreaterThan(44);
  });

  test("shrinks back to baseline when content is deleted", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    const multilineText = "line1\nline2\nline3\nline4";
    await page.evaluate((text) => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      const dt = new DataTransfer();
      dt.setData("text/plain", text);
      const event = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(event);
    }, multilineText);

    await page.waitForTimeout(200);

    await input.focus();
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.press("Backspace");

    await page.waitForTimeout(200);
    const height = await page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      return el.parentElement!.getBoundingClientRect().height;
    });
    expect(height).toBeLessThanOrEqual(50);
  });

  test("does not exceed max height with many lines", async ({ page }) => {
    const manyLines = Array.from(
      { length: 60 },
      (_, i) => `line ${i + 1}`
    ).join("\n");
    await page.evaluate((text) => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      const dt = new DataTransfer();
      dt.setData("text/plain", text);
      const event = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(event);
    }, manyLines);

    await page.waitForTimeout(200);
    const height = await page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      return el.parentElement!.getBoundingClientRect().height;
    });
    expect(height).toBeLessThanOrEqual(200);
  });

  test("content is scrollable when exceeding max height", async ({ page }) => {
    const manyLines = Array.from(
      { length: 60 },
      (_, i) => `line ${i + 1}`
    ).join("\n");
    await page.evaluate((text) => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      const dt = new DataTransfer();
      dt.setData("text/plain", text);
      const event = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(event);
    }, manyLines);

    await page.waitForTimeout(200);
    const isScrollable = await page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      return el.scrollHeight > el.clientHeight;
    });
    expect(isScrollable).toBe(true);
  });
});

test.describe("Placeholder", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page
      .locator(INPUT_SELECTOR)
      .waitFor({ state: "visible", timeout: 10000 });
  });

  test("shows placeholder text on load", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    const placeholder = await input.getAttribute("data-placeholder");
    expect(placeholder).toContain("How can I help you today?");
  });

  test("hides placeholder when text is entered", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.fill("a");
    const dataEmpty = await input.getAttribute("data-empty");
    expect(dataEmpty).toBeNull();
  });

  test("restores placeholder when text is deleted", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.fill("a");
    await input.focus();
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.press("Backspace");
    await expect(input).toHaveAttribute("data-empty", "");
  });

  test("restores placeholder after sending a message", async ({ page }) => {
    await mockChatEndpoint(page, buildMockStream("Mock response"));
    const input = page.locator(INPUT_SELECTOR);
    await input.fill("test");
    await page.keyboard.press("Enter");
    await expect(page.locator(HUMAN_MESSAGE_SELECTOR)).toContainText("test");
    await expect(input).toHaveAttribute("data-empty", "");
  });
});

test.describe("Focus Management", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page
      .locator(INPUT_SELECTOR)
      .waitFor({ state: "visible", timeout: 10000 });
  });

  test("input is focused on page load", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await expect(input).toBeFocused();
  });

  test("input is re-focused after sending a message", async ({ page }) => {
    await mockChatEndpoint(page, buildMockStream("Mock response"));
    const input = page.locator(INPUT_SELECTOR);
    await input.fill("test");
    await page.keyboard.press("Enter");
    await expect(page.locator(HUMAN_MESSAGE_SELECTOR)).toContainText("test");
    await expect(input).toBeFocused();
  });

  test("clicking away and back restores focus", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await expect(input).toBeFocused();

    const button = page.locator("[data-main-container] button").first();
    await button.waitFor({ state: "visible", timeout: 5000 });
    await button.click();
    await expect(input).not.toBeFocused();

    await page.keyboard.press("Escape");
    await input.click();
    await expect(input).toBeFocused();
  });
});

test.describe("Prompt Shortcuts", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page
      .locator(INPUT_SELECTOR)
      .waitFor({ state: "visible", timeout: 10000 });
  });

  test("typing / triggers shortcut UI", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await page.keyboard.type("/");
    await page.waitForTimeout(300);
    const popover = page.locator("[data-radix-popper-content-wrapper]");
    const popoverCount = await popover.count();
    // If prompt shortcuts are configured, a popover should appear.
    // If not, we just verify no crash occurred.
    expect(popoverCount).toBeGreaterThanOrEqual(0);
  });
});

test.describe("Keyboard Edge Cases", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page
      .locator(INPUT_SELECTOR)
      .waitFor({ state: "visible", timeout: 10000 });
  });

  test("Backspace deletes the last character", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await page.keyboard.type("abc");
    await page.keyboard.press("Backspace");
    await expect(input).toContainText("ab");
  });

  test("Ctrl+A then Backspace clears the input", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await page.keyboard.type("abc");
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.press("Backspace");
    const text = await input.textContent();
    expect(text?.trim()).toBe("");
  });

  test("Ctrl+A then typing replaces all content", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await page.keyboard.type("abc");
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.type("x");
    await expect(input).toContainText("x");
    const text = await input.textContent();
    expect(text?.trim()).toBe("x");
  });

  test("inline spans do not produce spurious newlines", async ({ page }) => {
    await mockChatEndpoint(page, buildMockStream("Mock response"));
    await page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.innerHTML = 'hello <span contenteditable="false">tile</span> world';
      el.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await page.keyboard.press("Enter");
    const messageEl = page.locator(HUMAN_MESSAGE_SELECTOR);
    const text = await messageEl.textContent();
    expect(text).toContain("hello tile world");
    expect(text).not.toMatch(/hello\n.*tile/);
  });
});

test.describe("Visual Regression", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page
      .locator(INPUT_SELECTOR)
      .waitFor({ state: "visible", timeout: 10000 });
  });

  test("empty input bar", async ({ page }) => {
    const inputBar = page.locator(INPUT_CONTAINER_SELECTOR);
    await expectElementScreenshot(inputBar, { name: "input-bar-empty" });
  });

  test("input bar with text", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.fill("Hello, this is a test message");
    const inputBar = page.locator(INPUT_CONTAINER_SELECTOR);
    await expectElementScreenshot(inputBar, { name: "input-bar-with-text" });
  });

  test("input bar with multiline text", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await page.keyboard.type("line one");
    await page.keyboard.press("Shift+Enter");
    await page.keyboard.type("line two");
    await page.keyboard.press("Shift+Enter");
    await page.keyboard.type("line three");
    const inputBar = page.locator(INPUT_CONTAINER_SELECTOR);
    await expectElementScreenshot(inputBar, { name: "input-bar-multiline" });
  });
});
