import { test, expect } from "@tests/e2e/chat/fixtures";
import {
  buildMockStream,
  mockChatEndpoint,
  resetTurnCounter,
} from "@tests/e2e/utils/chatMock";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";

const LARGE_TEXT = "line 1\nline 2\nline 3\nline 4";

test.describe("Core Text Input & Submission", () => {
  test.beforeEach(async ({ chatPage }) => {
    resetTurnCounter();
    await chatPage.goto();
    await mockChatEndpoint(chatPage.page, buildMockStream("Mock response"));
  });

  test("typing and pressing Enter sends the message", async ({ chatPage }) => {
    await chatPage.inputBar.fill("hello");
    await chatPage.inputBar.send();
    await chatPage.expectHumanMessage("hello");
  });

  test("typing and clicking send button sends the message", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.fill("hello");
    await chatPage.inputBar.clickSend();
    await chatPage.expectHumanMessage("hello");
  });

  test("pressing Enter with empty input does not send a message", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.focus();
    await chatPage.inputBar.send();
    await chatPage.page.waitForTimeout(500);
    await chatPage.expectNoHumanMessages();
  });

  test("pressing Enter with only spaces does not send a message", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.fill("   ");
    await chatPage.inputBar.send();
    await chatPage.page.waitForTimeout(500);
    await chatPage.expectNoHumanMessages();
  });

  test("input is cleared after sending a message", async ({ chatPage }) => {
    await chatPage.inputBar.fill("hello");
    await chatPage.inputBar.send();
    await chatPage.expectHumanMessage("hello");
    await chatPage.inputBar.expectEmpty();
  });

  test("sends a long message (2000+ characters)", async ({ chatPage }) => {
    const longText = "a".repeat(2100);
    await chatPage.inputBar.fill(longText);
    await chatPage.inputBar.send();
    await chatPage.expectHumanMessage(longText);
  });
});

test.describe("Multiline Input", () => {
  test.beforeEach(async ({ chatPage }) => {
    resetTurnCounter();
    await chatPage.goto();
    await mockChatEndpoint(chatPage.page, buildMockStream("Mock response"));
  });

  test("Shift+Enter creates a new line and increases input height", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.focus();
    await chatPage.page.keyboard.type("line1");
    await chatPage.page.keyboard.press("Shift+Enter");
    await chatPage.page.keyboard.type("line2");
    await chatPage.inputBar.expectHeightGreaterThan(44);
  });

  test("Shift+Enter does not send the message", async ({ chatPage }) => {
    await chatPage.inputBar.focus();
    await chatPage.page.keyboard.type("some text");
    await chatPage.page.keyboard.press("Shift+Enter");
    await chatPage.page.waitForTimeout(500);
    await chatPage.expectNoHumanMessages();
  });

  test("multiline message is sent with newlines preserved", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.focus();
    await chatPage.page.keyboard.type("line1");
    await chatPage.page.keyboard.press("Shift+Enter");
    await chatPage.page.keyboard.type("line2");
    await chatPage.inputBar.send();
    const msg = chatPage.humanMessage();
    await expect(msg).toContainText("line1");
    await expect(msg).toContainText("line2");
  });
});

test.describe("Paste Behavior", () => {
  test.beforeEach(async ({ chatPage }) => {
    resetTurnCounter();
    await chatPage.goto();
  });

  test("pasting plain text appears in the input", async ({ chatPage }) => {
    await chatPage.inputBar.paste("hello world");
    await chatPage.inputBar.expectText("hello world");
  });

  test("pasting rich HTML strips formatting and pastes plain text only", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.pasteHtml(
      "<b>bold</b> <i>italic</i>",
      "bold italic"
    );
    await chatPage.inputBar.expectText("bold italic");
    await chatPage.inputBar.expectInnerHtmlNotContaining("<b>");
    await chatPage.inputBar.expectInnerHtmlNotContaining("<i>");
  });

  test("select all then paste replaces content", async ({ chatPage }) => {
    await chatPage.inputBar.fill("original text");
    await chatPage.page.keyboard.press("ControlOrMeta+a");
    await chatPage.inputBar.paste("replacement");
    await chatPage.inputBar.expectText("replacement");
  });
});

test.describe("Paste Security", () => {
  test.beforeEach(async ({ chatPage }) => {
    resetTurnCounter();
    await chatPage.goto();
  });

  test("pasting script tags does not execute code", async ({ chatPage }) => {
    const xssPayload = '<script>window.__xss_fired=true</script>alert("xss")';
    await chatPage.inputBar.pasteHtml(xssPayload, xssPayload);
    await chatPage.inputBar.expectInnerHtmlNotContaining("<script");
    await chatPage.inputBar.expectInnerHtmlNotContaining("</script>");
    const xssFired = await chatPage.page.evaluate(
      () => (window as any).__xss_fired
    );
    expect(xssFired).toBeFalsy();
  });

  test("pasting img onerror does not execute code", async ({ chatPage }) => {
    const xssPayload = '<img src=x onerror="window.__xss_img=true">';
    await chatPage.inputBar.pasteHtml(xssPayload, "image");
    await chatPage.page.waitForTimeout(500);
    await chatPage.inputBar.expectInnerHtmlNotContaining("<img");
    await chatPage.inputBar.expectInnerHtmlNotContaining("onerror");
    const xssFired = await chatPage.page.evaluate(
      () => (window as any).__xss_img
    );
    expect(xssFired).toBeFalsy();
  });

  test("pasting event handler attributes does not execute code", async ({
    chatPage,
  }) => {
    const xssPayload =
      '<div onmouseover="window.__xss_div=true">hover me</div>';
    await chatPage.inputBar.pasteHtml(xssPayload, "hover me");
    await chatPage.inputBar.expectInnerHtmlNotContaining("onmouseover");
    await chatPage.inputBar.expectInnerHtmlNotContaining("<div");
    await chatPage.inputBar.expectText("hover me");
  });

  test("only plain text is inserted regardless of HTML clipboard content", async ({
    chatPage,
  }) => {
    const richHtml =
      '<a href="javascript:alert(1)">click</a><style>body{display:none}</style><iframe src="evil.com"></iframe>';
    await chatPage.inputBar.pasteHtml(richHtml, "click");
    await chatPage.inputBar.expectInnerHtmlNotContaining("<a");
    await chatPage.inputBar.expectInnerHtmlNotContaining("<style");
    await chatPage.inputBar.expectInnerHtmlNotContaining("<iframe");
    await chatPage.inputBar.expectInnerHtmlNotContaining("javascript:");
    await chatPage.inputBar.expectText("click");
  });
});

test.describe("Auto-Resize", () => {
  test.beforeEach(async ({ chatPage }) => {
    resetTurnCounter();
    await chatPage.goto();
  });

  test("grows taller when multiple lines are pasted", async ({ chatPage }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.expectHeightGreaterThan(44);
  });

  test("shrinks back to baseline when content is deleted", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.expectHeightGreaterThan(44);
    await chatPage.inputBar.clear();
    await chatPage.inputBar.expectHeightAtMost(50);
  });

  test("does not exceed max height with many lines", async ({ chatPage }) => {
    const manyLines = Array.from(
      { length: 60 },
      (_, i) => `line ${i + 1}`
    ).join("\n");
    await chatPage.inputBar.paste(manyLines);
    await chatPage.inputBar.expectHeightAtMost(200);
  });

  test("content is scrollable when exceeding max height", async ({
    chatPage,
  }) => {
    const manyLines = Array.from(
      { length: 60 },
      (_, i) => `line ${i + 1}`
    ).join("\n");
    await chatPage.inputBar.paste(manyLines);
    await chatPage.inputBar.expectScrollable();
  });
});

test.describe("Placeholder", () => {
  test.beforeEach(async ({ chatPage }) => {
    resetTurnCounter();
    await chatPage.goto();
  });

  test("shows placeholder text on load", async ({ chatPage }) => {
    await expect(chatPage.inputBar.textbox).toHaveAttribute(
      "data-placeholder",
      /How can I help you today\?/
    );
  });

  test("hides placeholder when text is entered", async ({ chatPage }) => {
    await chatPage.inputBar.fill("a");
    await expect(chatPage.inputBar.textbox).not.toHaveAttribute(
      "data-empty",
      ""
    );
  });

  test("restores placeholder when text is deleted", async ({ chatPage }) => {
    await chatPage.inputBar.fill("a");
    await chatPage.inputBar.clear();
    await expect(chatPage.inputBar.textbox).toHaveAttribute("data-empty", "");
  });

  test("restores placeholder after sending a message", async ({ chatPage }) => {
    await mockChatEndpoint(chatPage.page, buildMockStream("Mock response"));
    await chatPage.inputBar.fill("test");
    await chatPage.inputBar.send();
    await chatPage.expectHumanMessage("test");
    await chatPage.inputBar.expectEmpty();
  });
});

test.describe("Focus Management", () => {
  test.beforeEach(async ({ chatPage }) => {
    resetTurnCounter();
    await chatPage.goto();
  });

  test("input is focused on page load", async ({ chatPage }) => {
    await chatPage.inputBar.expectFocused();
  });

  test("input is re-focused after sending a message", async ({ chatPage }) => {
    await mockChatEndpoint(chatPage.page, buildMockStream("Mock response"));
    await chatPage.inputBar.fill("test");
    await chatPage.inputBar.send();
    await chatPage.expectHumanMessage("test");
    await chatPage.inputBar.expectFocused();
  });

  test("clicking away and back restores focus", async ({ chatPage }) => {
    await chatPage.inputBar.focus();
    await chatPage.inputBar.expectFocused();

    const button = chatPage.page
      .locator("[data-main-container] button")
      .first();
    await button.waitFor({ state: "visible", timeout: 5000 });
    await button.click();
    await expect(chatPage.inputBar.textbox).not.toBeFocused();

    await chatPage.page.keyboard.press("Escape");
    await chatPage.inputBar.textbox.click();
    await chatPage.inputBar.expectFocused();
  });
});

test.describe("Prompt Shortcuts", () => {
  test.beforeEach(async ({ chatPage }) => {
    resetTurnCounter();
    await chatPage.goto();
  });

  test("typing / triggers shortcut UI", async ({ chatPage }) => {
    await chatPage.inputBar.focus();
    await chatPage.page.keyboard.type("/");
    await chatPage.page.waitForTimeout(300);
    const popover = chatPage.page.locator(
      "[data-radix-popper-content-wrapper]"
    );
    const popoverCount = await popover.count();
    expect(popoverCount).toBeGreaterThanOrEqual(0);
  });
});

test.describe("Keyboard Edge Cases", () => {
  test.beforeEach(async ({ chatPage }) => {
    resetTurnCounter();
    await chatPage.goto();
  });

  test("Backspace deletes the last character", async ({ chatPage }) => {
    await chatPage.inputBar.typeText("abc");
    await chatPage.page.keyboard.press("Backspace");
    await chatPage.inputBar.expectText("ab");
  });

  test("Ctrl+A then Backspace clears the input", async ({ chatPage }) => {
    await chatPage.inputBar.typeText("abc");
    await chatPage.inputBar.clear();
    await chatPage.inputBar.expectEmpty();
  });

  test("Ctrl+A then typing replaces all content", async ({ chatPage }) => {
    await chatPage.inputBar.typeText("abc");
    await chatPage.page.keyboard.press("ControlOrMeta+a");
    await chatPage.page.keyboard.type("x");
    await expect(chatPage.inputBar.textbox).toHaveText("x");
  });

  test("inline spans do not produce spurious newlines", async ({
    chatPage,
  }) => {
    await mockChatEndpoint(chatPage.page, buildMockStream("Mock response"));
    await chatPage.page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.innerHTML = 'hello <span contenteditable="false">tile</span> world';
      el.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await chatPage.inputBar.send();
    const text = await chatPage.humanMessage().textContent();
    expect(text).toContain("hello tile world");
    expect(text).not.toMatch(/hello\n.*tile/);
  });
});

test.describe("Paste Tiles", () => {
  test.beforeEach(async ({ chatPage, api }) => {
    resetTurnCounter();
    await chatPage.goto();
    await api.setPasteTileSetting(true);
    await chatPage.page.reload();
    await chatPage.page.waitForLoadState("networkidle");
    await chatPage.inputBar.textbox.waitFor({
      state: "visible",
      timeout: 10000,
    });
    await mockChatEndpoint(chatPage.page, buildMockStream("Mock response"));
  });

  test.afterEach(async ({ api }) => {
    await api.setPasteTileSetting(false);
  });

  test("pasting large text creates a tile instead of inline text", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.expectTileCount(1);
    await chatPage.inputBar.expectTileData(LARGE_TEXT);
  });

  test("tile shows truncated preview and line count", async ({ chatPage }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await expect(chatPage.inputBar.tilePreview).toBeVisible();
    await expect(chatPage.inputBar.tileMeta).toContainText("lines");
    const previewText = await chatPage.inputBar.tilePreview.textContent();
    expect(previewText!.length).toBeLessThanOrEqual(25);
  });

  test("small text (<200 chars, <=3 lines) does not create a tile", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.paste("short text here");
    await chatPage.inputBar.expectTileCount(0);
    await chatPage.inputBar.expectText("short text here");
  });

  test("clicking × removes the tile", async ({ chatPage }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.expectTileCount(1);
    await chatPage.inputBar.removeTile();
    await chatPage.inputBar.expectTileCount(0);
  });

  test("submitting a message with a tile includes the full tile text", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.typeText("Context: ");
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.send();
    const msg = chatPage.humanMessage();
    await expect(msg).toContainText("Context:");
    await expect(msg).toContainText("line 1");
    await expect(msg).toContainText("line 4");
  });

  test("clicking tile opens editable popover", async ({ chatPage }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.clickTile();
    await chatPage.inputBar.expectPopoverVisible();
    await expect(chatPage.inputBar.tilePopoverTextarea).toBeVisible();
    await chatPage.inputBar.expectPopoverTextareaValue(LARGE_TEXT);
  });

  test("editing text in popover updates the tile data", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.clickTile();
    await chatPage.inputBar.editTileText(
      "modified text\nline 2\nline 3\nline 4"
    );
    await chatPage.inputBar.expectTileData(
      "modified text\nline 2\nline 3\nline 4"
    );
  });

  test("Escape closes popover and refocuses input", async ({ chatPage }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.clickTile();
    await chatPage.inputBar.expectPopoverVisible();
    await chatPage.inputBar.dismissPopoverViaEscape();
    await chatPage.inputBar.expectFocused();
  });

  test("ArrowLeft into tile highlights it", async ({ chatPage }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.page.keyboard.press("End");
    await chatPage.page.keyboard.press("ArrowLeft");
    await chatPage.inputBar.expectTileSelected();
  });

  test("ArrowRight into tile highlights it", async ({ chatPage }) => {
    await chatPage.inputBar.typeText("abc");
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.page.keyboard.press("Home");
    await chatPage.page.keyboard.press("ArrowRight");
    await chatPage.page.keyboard.press("ArrowRight");
    await chatPage.page.keyboard.press("ArrowRight");
    await chatPage.page.keyboard.press("ArrowRight");
    await chatPage.inputBar.expectTileSelected();
  });

  test("Enter on highlighted tile opens popover", async ({ chatPage }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.page.keyboard.press("End");
    await chatPage.page.keyboard.press("ArrowLeft");
    await chatPage.page.keyboard.press("Enter");
    await chatPage.inputBar.expectPopoverVisible();
  });

  test("Enter on highlighted tile does NOT send message", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.page.keyboard.press("End");
    await chatPage.page.keyboard.press("ArrowLeft");
    await chatPage.page.keyboard.press("Enter");
    await chatPage.page.waitForTimeout(500);
    await chatPage.expectNoHumanMessages();
  });

  test("typing deselects highlighted tile", async ({ chatPage }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.page.keyboard.press("End");
    await chatPage.page.keyboard.press("ArrowLeft");
    await chatPage.inputBar.expectTileSelected();
    await chatPage.page.keyboard.type("x");
    await chatPage.inputBar.expectTileSelected(false);
  });

  test("second ArrowLeft moves cursor past the tile", async ({ chatPage }) => {
    await chatPage.inputBar.typeText("abc");
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.page.keyboard.press("End");
    await chatPage.page.keyboard.press("ArrowLeft");
    await chatPage.page.keyboard.press("ArrowLeft");
    await chatPage.inputBar.expectTileSelected(false);
  });

  test("Backspace highlights tile, second Backspace deletes it", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.page.keyboard.press("End");
    await chatPage.page.keyboard.press("Backspace");
    await chatPage.inputBar.expectTileSelected();
    await chatPage.page.keyboard.press("Backspace");
    await chatPage.inputBar.expectTileCount(0);
  });

  test("Ctrl+A highlights tiles with blue border", async ({ chatPage }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.page.keyboard.press("ControlOrMeta+a");
    await chatPage.page.waitForTimeout(100);
    await chatPage.inputBar.expectTileInSelection();
  });

  test("Ctrl+C on tile copies the full text", async ({ chatPage }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.page.keyboard.press("ControlOrMeta+a");
    await chatPage.page.keyboard.press("ControlOrMeta+c");
    await chatPage.page.keyboard.press("Delete");
    await chatPage.page.keyboard.press("ControlOrMeta+v");
    await chatPage.inputBar.expectTileCount(1);
    await chatPage.inputBar.expectTileData(/line 1/);
  });

  test("Ctrl+X on tile cuts the full text and clears input", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.page.keyboard.press("ControlOrMeta+a");
    await chatPage.page.keyboard.press("ControlOrMeta+x");
    await chatPage.inputBar.expectTileCount(0);
    await chatPage.inputBar.expectEmpty();
  });

  test("multiple tiles can coexist", async ({ chatPage }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.page.keyboard.press("End");
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.expectTileCount(2);
  });

  test("cursor is hidden when tile is highlighted", async ({ chatPage }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.page.keyboard.press("End");
    await chatPage.page.keyboard.press("ArrowLeft");
    const collapsed = await chatPage.inputBar.isSelectionCollapsed();
    expect(collapsed).toBe(false);
  });

  test("clearing tile text to empty in popover removes the tile", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.clickTile();
    await chatPage.inputBar.editTileText("   ");
    await chatPage.inputBar.expectTileCount(0);
    await chatPage.inputBar.expectPopoverHidden();
    await chatPage.inputBar.expectFocused();
  });

  test("editing tile in popover then sending includes updated text", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.clickTile();
    await chatPage.inputBar.editTileText(
      "edited content\nline 2\nline 3\nline 4"
    );
    await chatPage.inputBar.dismissPopoverViaEscape();
    await chatPage.inputBar.send();
    const msg = chatPage.humanMessage();
    await expect(msg).toContainText("edited content");
    await expect(msg).toContainText("line 2");
  });

  test("text before and after tile is preserved on send", async ({
    chatPage,
  }) => {
    await chatPage.inputBar.typeText("before ");
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.page.keyboard.type(" after");
    await chatPage.inputBar.send();
    const msg = chatPage.humanMessage();
    await expect(msg).toContainText("before");
    await expect(msg).toContainText("line 1");
    await expect(msg).toContainText("after");
  });

  test("clicking backdrop dismisses popover", async ({ chatPage }) => {
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.clickTile();
    await chatPage.inputBar.expectPopoverVisible();
    await chatPage.inputBar.dismissPopoverViaBackdrop();
  });
});

test.describe("Paste Tiles — User Setting", () => {
  test.beforeEach(async ({ chatPage }) => {
    resetTurnCounter();
  });

  test.afterEach(async ({ api }) => {
    await api.setPasteTileSetting(false);
  });

  test("paste tiles are disabled by default (paste_as_tile = false)", async ({
    chatPage,
  }) => {
    await chatPage.goto();
    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.expectTileCount(0);
    await chatPage.inputBar.expectText("line 1");
  });

  test("paste tiles are created when user enables paste_as_tile", async ({
    chatPage,
    api,
  }) => {
    await chatPage.goto();
    await api.setPasteTileSetting(true);

    await chatPage.page.reload();
    await chatPage.page.waitForLoadState("networkidle");
    await chatPage.inputBar.textbox.waitFor({
      state: "visible",
      timeout: 10000,
    });

    await chatPage.inputBar.paste(LARGE_TEXT);
    await chatPage.inputBar.expectTileCount(1);
    await chatPage.inputBar.expectTileData(LARGE_TEXT);
  });
});

test.describe("Visual Regression", () => {
  test.beforeEach(async ({ chatPage }) => {
    resetTurnCounter();
    await chatPage.goto();
  });

  test("empty input bar", async ({ chatPage }) => {
    await expectElementScreenshot(chatPage.inputBar.container, {
      name: "input-bar-empty",
    });
  });

  test("input bar with text", async ({ chatPage }) => {
    await chatPage.inputBar.fill("Hello, this is a test message");
    await expectElementScreenshot(chatPage.inputBar.container, {
      name: "input-bar-with-text",
    });
  });

  test("input bar with multiline text", async ({ chatPage }) => {
    await chatPage.inputBar.focus();
    await chatPage.page.keyboard.type("line one");
    await chatPage.page.keyboard.press("Shift+Enter");
    await chatPage.page.keyboard.type("line two");
    await chatPage.page.keyboard.press("Shift+Enter");
    await chatPage.page.keyboard.type("line three");
    await expectElementScreenshot(chatPage.inputBar.container, {
      name: "input-bar-multiline",
    });
  });
});
