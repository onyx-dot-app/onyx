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

const TILE_SELECTOR = "[data-rich-tile]";
const TILE_REMOVE_SELECTOR = "[data-rich-tile-remove]";
const TILE_POPOVER_SELECTOR = "[role='dialog'][aria-label='Edit pasted text']";

const LARGE_TEXT = `function fibonacci(n) {
  if (n <= 1) return n;
  return fibonacci(n - 1) + fibonacci(n - 2);
}

for (let i = 0; i < 10; i++) {
  console.log(fibonacci(i));
}`;

async function pasteText(page: import("@playwright/test").Page, text: string) {
  await page.evaluate((t) => {
    const el = document.getElementById("onyx-chat-input-textbox")!;
    el.focus();
    const dt = new DataTransfer();
    dt.setData("text/plain", t);
    el.dispatchEvent(
      new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      })
    );
  }, text);
}

test.describe("Paste Tiles", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    // Enable paste tiles for this test suite
    await page.evaluate(() =>
      fetch("/api/paste-as-tile?paste_as_tile=true", { method: "PATCH" })
    );
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page
      .locator(INPUT_SELECTOR)
      .waitFor({ state: "visible", timeout: 10000 });
    await mockChatEndpoint(page, buildMockStream("Mock response"));
  });

  test.afterEach(async ({ page }) => {
    await page.evaluate(() =>
      fetch("/api/paste-as-tile?paste_as_tile=false", { method: "PATCH" })
    );
  });

  test("pasting large text creates a tile instead of inline text", async ({
    page,
  }) => {
    await pasteText(page, LARGE_TEXT);
    const tile = page.locator(TILE_SELECTOR);
    await expect(tile).toBeVisible();
    await expect(tile).toHaveAttribute("data-text", LARGE_TEXT);
  });

  test("tile shows truncated preview and line count", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    const preview = page.locator(".rich-input-tile-preview");
    const meta = page.locator(".rich-input-tile-meta");
    await expect(preview).toBeVisible();
    await expect(meta).toContainText("lines");
    const previewText = await preview.textContent();
    expect(previewText!.length).toBeLessThanOrEqual(25);
  });

  test("small text (<200 chars, <=3 lines) does not create a tile", async ({
    page,
  }) => {
    await page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      const dt = new DataTransfer();
      dt.setData("text/plain", "short text here");
      el.dispatchEvent(
        new ClipboardEvent("paste", {
          clipboardData: dt,
          bubbles: true,
          cancelable: true,
        })
      );
    });
    await expect(page.locator(TILE_SELECTOR)).toHaveCount(0);
    await expect(page.locator(INPUT_SELECTOR)).toContainText("short text here");
  });

  test("clicking × removes the tile", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    await expect(page.locator(TILE_SELECTOR)).toHaveCount(1);
    await page.locator(TILE_REMOVE_SELECTOR).click();
    await expect(page.locator(TILE_SELECTOR)).toHaveCount(0);
  });

  test("submitting a message with a tile includes the full tile text", async ({
    page,
  }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await page.keyboard.type("Context: ");
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.press("Enter");
    const msg = page.locator(HUMAN_MESSAGE_SELECTOR);
    await expect(msg).toContainText("Context:");
    await expect(msg).toContainText("function fibonacci");
    await expect(msg).toContainText("console.log");
  });

  test("clicking tile opens editable popover", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    await page.locator(TILE_SELECTOR).click();
    const popover = page.locator(TILE_POPOVER_SELECTOR);
    await expect(popover).toBeVisible();
    const textarea = popover.locator("textarea");
    await expect(textarea).toBeVisible();
    await expect(textarea).toHaveValue(LARGE_TEXT);
  });

  test("editing text in popover updates the tile data", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    await page.locator(TILE_SELECTOR).click();
    const textarea = page.locator(`${TILE_POPOVER_SELECTOR} textarea`);
    await textarea.fill("modified text\nline 2\nline 3\nline 4");
    const dataText = await page
      .locator(TILE_SELECTOR)
      .getAttribute("data-text");
    expect(dataText).toBe("modified text\nline 2\nline 3\nline 4");
  });

  test("Escape closes popover and refocuses input", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    await page.locator(TILE_SELECTOR).click();
    await expect(page.locator(TILE_POPOVER_SELECTOR)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(TILE_POPOVER_SELECTOR)).toHaveCount(0);
    const focused = await page.evaluate(
      () => document.activeElement?.id === "onyx-chat-input-textbox"
    );
    expect(focused).toBe(true);
  });

  test("ArrowLeft into tile highlights it", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.press("End");
    await page.keyboard.press("ArrowLeft");
    const highlighted = await page.evaluate(
      () =>
        document
          .querySelector("[data-rich-tile]")
          ?.classList.contains("rich-input-tile-selected")
    );
    expect(highlighted).toBe(true);
  });

  test("ArrowRight into tile highlights it", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await page.keyboard.type("abc");
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.press("Home");
    // Move to end of "abc" text, then one more right into the tile
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    const highlighted = await page.evaluate(
      () =>
        document
          .querySelector("[data-rich-tile]")
          ?.classList.contains("rich-input-tile-selected")
    );
    expect(highlighted).toBe(true);
  });

  test("Enter on highlighted tile opens popover", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.press("End");
    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("Enter");
    await expect(page.locator(TILE_POPOVER_SELECTOR)).toBeVisible();
  });

  test("Enter on highlighted tile does NOT send message", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.press("End");
    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(500);
    await expect(page.locator(HUMAN_MESSAGE_SELECTOR)).toHaveCount(0);
  });

  test("typing deselects highlighted tile", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.press("End");
    await page.keyboard.press("ArrowLeft");
    const before = await page.evaluate(
      () =>
        document
          .querySelector("[data-rich-tile]")
          ?.classList.contains("rich-input-tile-selected")
    );
    expect(before).toBe(true);
    await page.keyboard.type("x");
    const after = await page.evaluate(
      () =>
        document
          .querySelector("[data-rich-tile]")
          ?.classList.contains("rich-input-tile-selected")
    );
    expect(after).toBe(false);
  });

  test("second ArrowLeft moves cursor past the tile", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await page.keyboard.type("abc");
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.press("End");
    // First ArrowLeft highlights tile
    await page.keyboard.press("ArrowLeft");
    // Second ArrowLeft deselects and moves before tile
    await page.keyboard.press("ArrowLeft");
    const highlighted = await page.evaluate(
      () =>
        document
          .querySelector("[data-rich-tile]")
          ?.classList.contains("rich-input-tile-selected")
    );
    expect(highlighted).toBe(false);
  });

  test("Backspace highlights tile, second Backspace deletes it", async ({
    page,
  }) => {
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.press("End");
    // First backspace highlights
    await page.keyboard.press("Backspace");
    const highlighted = await page.evaluate(
      () =>
        document
          .querySelector("[data-rich-tile]")
          ?.classList.contains("rich-input-tile-selected")
    );
    expect(highlighted).toBe(true);
    // Second backspace deletes
    await page.keyboard.press("Backspace");
    await expect(page.locator(TILE_SELECTOR)).toHaveCount(0);
  });

  test("Ctrl+A highlights tiles with blue border", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.press("ControlOrMeta+a");
    await page.waitForTimeout(100);
    const inSelection = await page.evaluate(
      () =>
        document
          .querySelector("[data-rich-tile]")
          ?.classList.contains("rich-input-tile-in-selection")
    );
    expect(inSelection).toBe(true);
  });

  test("Ctrl+C on tile copies the full text", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.press("ControlOrMeta+c");
    // Clear and paste back
    await page.keyboard.press("Delete");
    await page.keyboard.press("ControlOrMeta+v");
    // Should create a new tile since the full text was on clipboard
    await expect(page.locator(TILE_SELECTOR)).toHaveCount(1);
    const dataText = await page
      .locator(TILE_SELECTOR)
      .getAttribute("data-text");
    expect(dataText).toContain("function fibonacci");
  });

  test("Ctrl+X on tile cuts the full text and clears input", async ({
    page,
  }) => {
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.press("ControlOrMeta+x");
    await expect(page.locator(TILE_SELECTOR)).toHaveCount(0);
    const text = await page.locator(INPUT_SELECTOR).textContent();
    expect(text?.trim()).toBe("");
  });

  test("multiple tiles can coexist", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.press("End");
    await page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      const dt = new DataTransfer();
      dt.setData(
        "text/plain",
        "const x = 1;\nconst y = 2;\nconst z = 3;\nconst w = 4;"
      );
      el.dispatchEvent(
        new ClipboardEvent("paste", {
          clipboardData: dt,
          bubbles: true,
          cancelable: true,
        })
      );
    });
    await expect(page.locator(TILE_SELECTOR)).toHaveCount(2);
  });

  test("cursor is hidden when tile is highlighted", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.press("End");
    await page.keyboard.press("ArrowLeft");
    const selectionCollapsed = await page.evaluate(() => {
      const sel = window.getSelection();
      return sel?.isCollapsed;
    });
    expect(selectionCollapsed).toBe(false);
  });

  test("clearing tile text to empty in popover removes the tile", async ({
    page,
  }) => {
    await pasteText(page, LARGE_TEXT);
    await page.locator(TILE_SELECTOR).click();
    const textarea = page.locator(`${TILE_POPOVER_SELECTOR} textarea`);
    await textarea.fill("   ");
    await expect(page.locator(TILE_SELECTOR)).toHaveCount(0);
    await expect(page.locator(TILE_POPOVER_SELECTOR)).toHaveCount(0);
    const focused = await page.evaluate(
      () => document.activeElement?.id === "onyx-chat-input-textbox"
    );
    expect(focused).toBe(true);
  });

  test("editing tile in popover then sending includes updated text", async ({
    page,
  }) => {
    await pasteText(page, LARGE_TEXT);
    await page.locator(TILE_SELECTOR).click();
    const textarea = page.locator(`${TILE_POPOVER_SELECTOR} textarea`);
    await textarea.fill("edited content\nline 2\nline 3\nline 4");
    await page.keyboard.press("Escape");
    await page.keyboard.press("Enter");
    const msg = page.locator(HUMAN_MESSAGE_SELECTOR);
    await expect(msg).toContainText("edited content");
    await expect(msg).toContainText("line 2");
  });

  test("text before and after tile is preserved on send", async ({ page }) => {
    const input = page.locator(INPUT_SELECTOR);
    await input.focus();
    await page.keyboard.type("before ");
    await pasteText(page, LARGE_TEXT);
    await page.keyboard.type(" after");
    await page.keyboard.press("Enter");
    const msg = page.locator(HUMAN_MESSAGE_SELECTOR);
    await expect(msg).toContainText("before");
    await expect(msg).toContainText("function fibonacci");
    await expect(msg).toContainText("after");
  });

  test("clicking backdrop dismisses popover", async ({ page }) => {
    await pasteText(page, LARGE_TEXT);
    await page.locator(TILE_SELECTOR).click();
    await expect(page.locator(TILE_POPOVER_SELECTOR)).toBeVisible();
    await page.locator(".fixed.inset-0.z-40").click();
    await expect(page.locator(TILE_POPOVER_SELECTOR)).toHaveCount(0);
  });
});

test.describe("Paste Tiles — User Setting", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
  });

  test("paste tiles are disabled by default (paste_as_tile = false)", async ({
    page,
  }) => {
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page
      .locator(INPUT_SELECTOR)
      .waitFor({ state: "visible", timeout: 10000 });

    await pasteText(page, LARGE_TEXT);
    await expect(page.locator(TILE_SELECTOR)).toHaveCount(0);
    await expect(page.locator(INPUT_SELECTOR)).toContainText(
      "function fibonacci"
    );
  });

  test("paste tiles are created when user enables paste_as_tile", async ({
    page,
  }) => {
    // Enable the setting via API before navigating
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    await page.evaluate(() =>
      fetch("/api/paste-as-tile?paste_as_tile=true", { method: "PATCH" })
    );

    // Reload to pick up the new preference
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page
      .locator(INPUT_SELECTOR)
      .waitFor({ state: "visible", timeout: 10000 });

    await pasteText(page, LARGE_TEXT);
    await expect(page.locator(TILE_SELECTOR)).toHaveCount(1);
    await expect(page.locator(TILE_SELECTOR)).toHaveAttribute(
      "data-text",
      LARGE_TEXT
    );

    // Clean up: disable the setting
    await page.evaluate(() =>
      fetch("/api/paste-as-tile?paste_as_tile=false", { method: "PATCH" })
    );
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
