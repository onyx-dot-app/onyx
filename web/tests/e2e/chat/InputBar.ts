/**
 * Page Object Model for the chat input bar.
 *
 * Encapsulates locators and interactions for the contentEditable input,
 * paste tiles, tile popover, and resize behavior. Designed to be
 * instantiated on ChatPage as `chatPage.inputBar`.
 */

import { type Page, type Locator, expect } from "@playwright/test";

const POLL_TIMEOUT = 5000;

/**
 * Auto-retrying assertion for values that have no built-in Playwright
 * locator assertion (e.g. computed heights, scrollHeight comparisons,
 * innerHTML checks). Prefer locator assertions like `toHaveClass`,
 * `toHaveAttribute`, `toContainText` when one exists — they are
 * faster and produce better error messages.
 */
function poll<T>(fn: () => Promise<T>) {
  return expect.poll(fn, { timeout: POLL_TIMEOUT });
}

export class InputBar {
  readonly page: Page;

  readonly container: Locator;
  readonly textbox: Locator;
  readonly sendButton: Locator;
  readonly processingFileChips: Locator;
  readonly queuedMessages: Locator;
  readonly pendingMessageHint: Locator;
  readonly subagentActivity: Locator;
  readonly composerSendNowButton: Locator;

  readonly tile: Locator;
  readonly tileRemoveButton: Locator;
  readonly tilePopover: Locator;
  readonly tilePopoverTextarea: Locator;
  readonly tilePopoverBackdrop: Locator;
  readonly tilePopoverExpandButton: Locator;
  readonly tilePreview: Locator;
  readonly tileMeta: Locator;

  constructor(page: Page) {
    this.page = page;
    this.container = page.locator("#onyx-chat-input");
    this.textbox = page.locator("#onyx-chat-input-textbox");
    this.sendButton = page.locator("#onyx-chat-input-send-button");
    this.processingFileChips = this.container.getByText("Processing...");
    this.subagentActivity = page.getByTestId("subagent-activity");
    this.queuedMessages = page.getByTestId("queued-message-bar");
    this.pendingMessageHint = this.container.getByTestId(
      "pending-message-hint"
    );
    this.composerSendNowButton = this.container.getByRole("button", {
      name: "Send now",
      exact: true,
    });

    this.tile = page.locator("[data-rich-tile]");
    this.tileRemoveButton = page.locator("[data-rich-tile-remove]");
    this.tilePopover = page.locator(
      "[role='dialog'][aria-label='Edit pasted text']"
    );
    this.tilePopoverTextarea = this.tilePopover.locator("textarea");
    this.tilePopoverBackdrop = page.getByTestId("paste-tile-backdrop");
    this.tilePopoverExpandButton = this.tilePopover.getByRole("button", {
      name: "Expand into input bar",
    });
    this.tilePreview = page.locator(".rich-input-tile-preview");
    this.tileMeta = page.locator(".rich-input-tile-meta");
  }

  // ---------------------------------------------------------------------------
  // Text input
  // ---------------------------------------------------------------------------

  async fill(text: string): Promise<void> {
    await this.textbox.fill(text);
  }

  async typeText(text: string): Promise<void> {
    await this.textbox.focus();
    await this.page.keyboard.type(text);
  }

  async focus(): Promise<void> {
    await this.textbox.focus();
  }

  async expectCompactSubagentActivity(): Promise<void> {
    await poll(() =>
      this.subagentActivity.evaluate((element) => {
        const dot = element.firstElementChild;
        const label = element.lastElementChild;
        if (!dot || !label) return false;
        const composer = document.getElementById("onyx-chat-input");
        if (!composer || !composer.contains(element)) return false;
        const dotBox = dot.getBoundingClientRect();
        const labelBox = label.getBoundingClientRect();
        const lineHeight = Number.parseFloat(
          getComputedStyle(label).lineHeight
        );
        const style = getComputedStyle(element);
        const padding =
          Number.parseFloat(style.paddingTop) +
          Number.parseFloat(style.paddingBottom);
        return (
          Math.abs(
            element.getBoundingClientRect().x +
              element.getBoundingClientRect().width / 2 -
              (composer.getBoundingClientRect().x +
                composer.getBoundingClientRect().width / 2)
          ) < 1 &&
          dotBox.right <= labelBox.left &&
          Math.abs(
            dotBox.y + dotBox.height / 2 - labelBox.y - labelBox.height / 2
          ) < 1 &&
          labelBox.height <= lineHeight &&
          element.getBoundingClientRect().height <= lineHeight + padding
        );
      })
    ).toBe(true);
  }

  async expectInlinePendingMessageHint(): Promise<void> {
    await poll(() =>
      this.pendingMessageHint.evaluate((element) => {
        const boxes = Array.from(element.children, (child) =>
          child.getBoundingClientRect()
        );
        const first = boxes[0];
        return (
          boxes.length === 5 &&
          first !== undefined &&
          boxes.every(
            (box) =>
              Math.abs(box.y + box.height / 2 - first.y - first.height / 2) < 1
          )
        );
      })
    ).toBe(true);
  }

  async clear(): Promise<void> {
    await this.textbox.focus();
    await this.page.keyboard.press("ControlOrMeta+a");
    await this.page.keyboard.press("Backspace");
  }

  // ---------------------------------------------------------------------------
  // Paste
  // ---------------------------------------------------------------------------

  async paste(text: string): Promise<void> {
    await this.page.evaluate((t) => {
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

  async pastePlain(text: string): Promise<void> {
    await this.page.evaluate((t) => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      el.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "V",
          code: "KeyV",
          ctrlKey: true,
          shiftKey: true,
          bubbles: true,
          cancelable: true,
        })
      );
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

  async armPlainPaste(): Promise<void> {
    await this.page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      el.focus();
      el.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "V",
          code: "KeyV",
          ctrlKey: true,
          shiftKey: true,
          bubbles: true,
          cancelable: true,
        })
      );
    });
  }

  async pasteHtml(html: string, plainText: string): Promise<void> {
    await this.page.evaluate(
      ({ html, plain }) => {
        const el = document.getElementById("onyx-chat-input-textbox")!;
        el.focus();
        const dt = new DataTransfer();
        dt.setData("text/html", html);
        dt.setData("text/plain", plain);
        el.dispatchEvent(
          new ClipboardEvent("paste", {
            clipboardData: dt,
            bubbles: true,
            cancelable: true,
          })
        );
      },
      { html, plain: plainText }
    );
  }

  // ---------------------------------------------------------------------------
  // Submission
  // ---------------------------------------------------------------------------

  async send(): Promise<void> {
    await this.page.keyboard.press("Enter");
  }

  async submitPending(
    text: string,
    delivery: "queue" | "send" = "queue"
  ): Promise<void> {
    await this.textbox.fill(text);
    await this.textbox.press(
      delivery === "queue" ? "ControlOrMeta+Enter" : "Enter"
    );
    await expect(this.textbox).toHaveText("");
  }

  async discardPending(index: number): Promise<void> {
    await this.queuedMessages.nth(index).click();
    await this.textbox.press("Delete");
  }

  async editPending(index: number): Promise<void> {
    await this.queuedMessages
      .nth(index)
      .getByRole("button", { name: "Edit queued message", exact: true })
      .click();
  }

  async sendPendingNow(index: number): Promise<void> {
    const queuedMessage = this.queuedMessages.nth(index);
    await queuedMessage.click();
    await queuedMessage
      .getByRole("button", { name: "Send now", exact: true })
      .click();
  }

  async clickSend(): Promise<void> {
    await this.sendButton.click();
  }

  // ---------------------------------------------------------------------------
  // Tile interactions
  // ---------------------------------------------------------------------------

  async clickTile(index = 0): Promise<void> {
    await this.tile.nth(index).click();
  }

  async removeTile(index = 0): Promise<void> {
    await this.tileRemoveButton.nth(index).click();
  }

  async editTileText(newText: string): Promise<void> {
    await this.tilePopoverTextarea.fill(newText);
  }

  async expandTileViaPopover(): Promise<void> {
    await this.tilePopoverExpandButton.click();
  }

  async dismissPopoverViaEscape(): Promise<void> {
    await this.page.keyboard.press("Escape");
    await expect(this.tilePopover).toHaveCount(0);
  }

  async dismissPopoverViaBackdrop(): Promise<void> {
    await this.tilePopoverBackdrop.click();
    await expect(this.tilePopover).toHaveCount(0);
  }

  // ---------------------------------------------------------------------------
  // Assertions
  // ---------------------------------------------------------------------------

  async expectFocused(): Promise<void> {
    await expect(this.textbox).toBeFocused();
  }

  async expectFileProcessing(processing = true): Promise<void> {
    if (processing) {
      await expect(this.processingFileChips.first()).toBeVisible();
    } else {
      await expect(this.processingFileChips).toHaveCount(0, {
        timeout: 10000,
      });
    }
  }

  async expectEmpty(): Promise<void> {
    await expect(this.textbox).toHaveAttribute("data-empty", "");
  }

  async expectText(text: string): Promise<void> {
    await expect(this.textbox).toContainText(text);
  }

  async expectNoText(text: string): Promise<void> {
    await expect(this.textbox).not.toContainText(text);
  }

  async expectTileCount(count: number): Promise<void> {
    await expect(this.tile).toHaveCount(count);
  }

  async expectTileData(text: string | RegExp, index = 0): Promise<void> {
    await expect(this.tile.nth(index)).toHaveAttribute("data-text", text);
  }

  async expectTileSelected(selected = true): Promise<void> {
    const assertion = expect(this.tile.first());
    if (selected) {
      await assertion.toHaveClass(/rich-input-tile-selected/);
    } else {
      await assertion.not.toHaveClass(/rich-input-tile-selected/);
    }
  }

  async expectTileInSelection(inSelection = true): Promise<void> {
    const assertion = expect(this.tile.first());
    if (inSelection) {
      await assertion.toHaveClass(/rich-input-tile-in-selection/);
    } else {
      await assertion.not.toHaveClass(/rich-input-tile-in-selection/);
    }
  }

  async expectPopoverVisible(): Promise<void> {
    await expect(this.tilePopover).toBeVisible();
  }

  async expectPopoverHidden(): Promise<void> {
    await expect(this.tilePopover).toHaveCount(0);
  }

  async expectPopoverTextareaValue(value: string): Promise<void> {
    await expect(this.tilePopoverTextarea).toHaveValue(value);
  }

  private getWrapperHeight(): Promise<number> {
    return this.page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      return el.parentElement!.getBoundingClientRect().height;
    });
  }

  async expectHeightGreaterThan(min: number): Promise<void> {
    await poll(() => this.getWrapperHeight()).toBeGreaterThan(min);
  }

  async expectHeightAtMost(max: number): Promise<void> {
    await poll(() => this.getWrapperHeight()).toBeLessThanOrEqual(max);
  }

  async expectScrollable(): Promise<void> {
    await poll(() =>
      this.page.evaluate(() => {
        const el = document.getElementById("onyx-chat-input-textbox")!;
        return el.scrollHeight > el.clientHeight;
      })
    ).toBe(true);
  }

  /** Returns the selection collapsed state (false means something is selected). */
  async isSelectionCollapsed(): Promise<boolean> {
    return this.page.evaluate(() => {
      const sel = window.getSelection();
      return sel?.isCollapsed ?? true;
    });
  }

  async expectInnerHtmlNotContaining(text: string): Promise<void> {
    await poll(() => this.textbox.innerHTML()).not.toContain(text);
  }
}
