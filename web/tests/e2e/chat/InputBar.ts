/**
 * Page Object Model for the chat input bar.
 *
 * Encapsulates locators and interactions for the contentEditable input,
 * paste tiles, tile popover, and resize behavior. Designed to be
 * instantiated on ChatPage as `chatPage.inputBar`.
 */

import { type Page, type Locator, expect } from "@playwright/test";

export class InputBar {
  readonly page: Page;

  readonly container: Locator;
  readonly textbox: Locator;
  readonly sendButton: Locator;

  readonly tile: Locator;
  readonly tileRemoveButton: Locator;
  readonly tilePopover: Locator;
  readonly tilePopoverTextarea: Locator;
  readonly tilePopoverBackdrop: Locator;
  readonly tilePreview: Locator;
  readonly tileMeta: Locator;

  constructor(page: Page) {
    this.page = page;
    this.container = page.locator("#onyx-chat-input");
    this.textbox = page.locator("#onyx-chat-input-textbox");
    this.sendButton = page.locator("#onyx-chat-input-send-button");

    this.tile = page.locator("[data-rich-tile]");
    this.tileRemoveButton = page.locator("[data-rich-tile-remove]");
    this.tilePopover = page.locator(
      "[role='dialog'][aria-label='Edit pasted text']"
    );
    this.tilePopoverTextarea = this.tilePopover.locator("textarea");
    this.tilePopoverBackdrop = page.getByTestId("paste-tile-backdrop");
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

  async dismissPopoverViaEscape(): Promise<void> {
    await this.page.keyboard.press("Escape");
    await expect(this.tilePopover).toHaveCount(0);
  }

  async dismissPopoverViaBackdrop(): Promise<void> {
    await this.tilePopoverBackdrop.click();
    await expect(this.tilePopover).toHaveCount(0);
  }

  // ---------------------------------------------------------------------------
  // Keyboard navigation into tiles
  // ---------------------------------------------------------------------------

  async arrowLeftIntoTile(): Promise<void> {
    await this.page.keyboard.press("End");
    await this.page.keyboard.press("ArrowLeft");
  }

  // ---------------------------------------------------------------------------
  // Assertions
  // ---------------------------------------------------------------------------

  async expectFocused(): Promise<void> {
    await expect(this.textbox).toBeFocused();
  }

  async expectEmpty(): Promise<void> {
    await expect(this.textbox).toHaveAttribute("data-empty", "");
    const text = await this.textbox.textContent();
    expect(text?.trim()).toBe("");
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
    const hasClass = await this.page.evaluate(
      () =>
        document
          .querySelector("[data-rich-tile]")
          ?.classList.contains("rich-input-tile-selected")
    );
    expect(hasClass).toBe(selected);
  }

  async expectTileInSelection(inSelection = true): Promise<void> {
    const hasClass = await this.page.evaluate(
      () =>
        document
          .querySelector("[data-rich-tile]")
          ?.classList.contains("rich-input-tile-in-selection")
    );
    expect(hasClass).toBe(inSelection);
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

  /** Returns the wrapper element's computed height. */
  async getWrapperHeight(): Promise<number> {
    return this.page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      return el.parentElement!.getBoundingClientRect().height;
    });
  }

  async expectHeightGreaterThan(min: number): Promise<void> {
    const height = await this.getWrapperHeight();
    expect(height).toBeGreaterThan(min);
  }

  async expectHeightAtMost(max: number): Promise<void> {
    const height = await this.getWrapperHeight();
    expect(height).toBeLessThanOrEqual(max);
  }

  async expectScrollable(): Promise<void> {
    const isScrollable = await this.page.evaluate(() => {
      const el = document.getElementById("onyx-chat-input-textbox")!;
      return el.scrollHeight > el.clientHeight;
    });
    expect(isScrollable).toBe(true);
  }

  /** Returns the selection collapsed state (false means something is selected). */
  async isSelectionCollapsed(): Promise<boolean> {
    return this.page.evaluate(() => {
      const sel = window.getSelection();
      return sel?.isCollapsed ?? true;
    });
  }

  async expectInnerHtmlNotContaining(text: string): Promise<void> {
    const innerHTML = await this.textbox.innerHTML();
    expect(innerHTML).not.toContain(text);
  }
}
