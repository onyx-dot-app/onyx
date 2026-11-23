/**
 * Page Object Model for the main chat page (/app).
 *
 * Encapsulates locators and interactions shared across chat specs so that
 * individual tests remain declarative.
 */

import { type Page, type Locator, expect } from "@playwright/test";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";
import { InputBar } from "@tests/e2e/chat/InputBar";

interface SavedChatMessage {
  message_type: string;
  message: string;
}

/**
 * The right panel's drawn box, the page column's width and the workspace
 * row's box in one frame, in pixels.
 */
export interface PanelFrame {
  start: number;
  end: number;
  width: number;
  pageWidth: number;
  rowStart: number;
  rowEnd: number;
}

export class ChatPage {
  readonly page: Page;
  readonly inputBar: InputBar;

  // Layout containers
  readonly container: Locator;
  readonly scrollContainer: Locator;

  // Message collections. Only messages near the viewport are mounted, so
  // these hold the rendered ones, not the whole chat.
  readonly humanMessages: Locator;
  readonly humanMessageBubbles: Locator;
  readonly aiMessages: Locator;
  readonly agentResultsDividers: Locator;
  /** One row per message; far from the viewport, an empty placeholder. */
  readonly messageRows: Locator;
  readonly scrollToBottomButton: Locator;
  readonly usageLimitBanner: Locator;
  readonly errorBanners: Locator;
  /** The toggle at the header's end that opens and closes the right panel. */
  readonly rightPanelToggle: Locator;
  readonly publishedFilesPanel: Locator;
  /** A file tab's Download button, in the right panel's URL bar. */
  readonly rightPanelDownload: Locator;

  // Model picker: the "Add Model" button, then one pill per selected model
  readonly modelSelector: Locator;
  /** A pill opens its switch list, where a row replaces that model. */
  readonly modelPills: Locator;
  readonly modelPopover: Locator;
  readonly modelSearchInput: Locator;
  /** Rows of the open list, each "selected" or "empty". */
  readonly modelOptions: Locator;
  readonly selectedModelOptions: Locator;
  readonly unselectedModelOptions: Locator;

  constructor(page: Page) {
    this.page = page;
    this.inputBar = new InputBar(page);
    this.container = page.locator("[data-main-container]");
    this.scrollContainer = page.getByTestId("chat-scroll-container");
    this.humanMessages = page.locator("#onyx-human-message");
    this.humanMessageBubbles = page.getByTestId("human-message-bubble");
    this.aiMessages = page.getByTestId("onyx-ai-message");
    this.agentResultsDividers = this.scrollContainer.getByText(
      "Subagent results received",
      { exact: true }
    );
    this.messageRows = this.scrollContainer.locator('[id^="message-"]');
    this.scrollToBottomButton = page.getByRole("button", {
      name: "Scroll to bottom",
    });
    this.usageLimitBanner = page.getByText(/you've reached the usage budget/i);
    this.errorBanners = page.getByTestId("chat-error-banner");
    this.rightPanelToggle = page.getByRole("button", {
      name: "Toggle panel",
    });
    this.publishedFilesPanel = page.getByRole("complementary", {
      name: "Files",
    });
    this.rightPanelDownload = this.publishedFilesPanel.getByRole("button", {
      name: "Download file",
    });
    this.modelSelector = page.getByTestId("model-selector");
    this.modelPills = this.modelSelector.locator(
      "button:not([aria-label='Add Model'])"
    );
    this.modelPopover = page.getByRole("dialog");
    this.modelSearchInput =
      this.modelPopover.getByPlaceholder("Search models...");
    this.modelOptions = this.modelPopover.locator("[data-interactive-state]");
    this.selectedModelOptions = this.modelPopover.locator(
      '[data-interactive-state="selected"]'
    );
    this.unselectedModelOptions = this.modelPopover.locator(
      '[data-interactive-state="empty"]'
    );
  }

  humanMessage(index = 0): Locator {
    return this.humanMessages.nth(index);
  }

  aiMessage(index = 0): Locator {
    return this.aiMessages.nth(index);
  }

  /** Images a tool generated for an AI message, shown at the top of its answer. */
  generatedImages(index = 0): Locator {
    return this.aiMessage(index).getByRole("img", {
      name: "Chat attachment",
      exact: true,
    });
  }

  /** The download cards of the files that an AI message published. */
  publishedFileCards(index = 0): Locator {
    return this.aiMessage(index).getByRole("button", { name: /^Preview / });
  }

  /** A published file's card, by the title it shows (else its file name). */
  publishedFileCard(title: string, index = 0): Locator {
    return this.publishedFileCards(index).filter({ hasText: title });
  }

  /** Opens all of an AI message's published files in the panel. */
  async viewAllPublishedFiles(count: number, index = 0): Promise<void> {
    await this.aiMessage(index)
      .getByRole("button", { name: `View all ${count} files` })
      .click();
  }

  /** Checks a published file's card: its details and download link. */
  async expectPublishedFile(
    title: string,
    {
      fileName,
      details,
      href,
    }: { fileName: string; details: RegExp; href: string },
    index = 0
  ): Promise<void> {
    const card = this.publishedFileCard(title, index);
    await expect(card).toBeVisible();
    await expect(card).toHaveAccessibleName(`Preview ${fileName}`);
    await expect(card).toContainText(details);
    const download = card.getByRole("link", { name: "Download" });
    await expect(download).toHaveAttribute("href", href);
    await expect(download).toHaveAttribute("download", fileName);
  }

  /** A published file's preview in the Files panel, by its title or name. */
  publishedFilePreview(title: string): Locator {
    return this.publishedFilesPanel.getByRole("region", {
      name: `Preview of ${title}`,
    });
  }

  /**
   * Opens a reply card's file in the right panel and checks that markdown
   * shows as a document: its heading, not the source.
   */
  async expectMarkdownPreview(title: string, heading: string): Promise<void> {
    await this.publishedFileCard(title).click();
    const preview = this.publishedFilePreview(title);
    await expect(preview.getByRole("heading", { name: heading })).toBeVisible();
    await expect(preview).not.toContainText(`# ${heading}`);
  }

  /**
   * Opens a reply card's file in the right panel and checks that it shows as
   * a grid with `cell` in one cell.
   */
  async expectSpreadsheetPreview(title: string, cell: string): Promise<void> {
    await this.publishedFileCard(title).click();
    const preview = this.publishedFilePreview(title);
    await expect(
      preview.getByRole("cell", { name: cell, exact: true })
    ).toBeVisible();
  }

  /**
   * Opens a reply card's PDF in the right panel, checks that its first page
   * draws, and pages to its last page.
   */
  async expectPdfPreview(title: string, pageCount: number): Promise<void> {
    await this.publishedFileCard(title).click();
    const preview = this.publishedFilePreview(title);
    const controls = preview.getByRole("toolbar", { name: "PDF controls" });
    await expect(controls).toContainText(`1 / ${pageCount}`);
    await expect(
      preview.getByRole("region", { name: "Page 1 preview" }).locator("canvas")
    ).toBeVisible();
    for (let page = 2; page <= pageCount; page++) {
      await controls.getByRole("button", { name: "Next page" }).click();
      await expect(controls).toContainText(`${page} / ${pageCount}`);
    }
    await expect(
      controls.getByRole("button", { name: "Next page" })
    ).toBeDisabled();
    await expect(this.rightPanelDownload).toBeVisible();
  }

  /**
   * Opens a reply card's PowerPoint deck in the right panel and checks its
   * slides: the first shows `firstSlideText`, and the arrows step through
   * the rest.
   */
  async expectPptxPreview(
    title: string,
    slideCount: number,
    firstSlideText: string
  ): Promise<void> {
    await this.publishedFileCard(title).click();
    const preview = this.publishedFilePreview(title);
    const controls = preview.getByRole("toolbar", {
      name: "Presentation controls",
    });
    await expect(controls).toContainText(`Slide 1 of ${slideCount}`);
    await expect(
      preview.getByRole("region", { name: `Slide 1 of ${slideCount}` })
    ).toContainText(firstSlideText);
    await expect(
      preview
        .getByRole("toolbar", { name: "Slides" })
        .getByRole("button", { name: /^Slide \d+ of/ })
    ).toHaveCount(slideCount);
    for (let slide = 2; slide <= slideCount; slide++) {
      await controls.getByRole("button", { name: "Next slide" }).click();
      await expect(controls).toContainText(`Slide ${slide} of ${slideCount}`);
    }
    await expect(this.rightPanelDownload).toBeVisible();
  }

  /**
   * Opens a reply card's Word file in the right panel and checks that its
   * first page fits the panel's width. The page scale settles after the
   * pages insert, so the width is read again on each try.
   */
  async expectDocxPreviewFitsPanel(title: string): Promise<void> {
    await this.publishedFileCard(title).click();
    const preview = this.publishedFilePreview(title);
    const firstPage = preview.locator("section.docx").first();
    await expect(firstPage).toBeVisible();
    await expect
      .poll(async () => {
        const [previewBox, pageBox] = await Promise.all([
          preview.boundingBox(),
          firstPage.boundingBox(),
        ]);
        return (
          previewBox !== null &&
          pageBox !== null &&
          pageBox.width <= previewBox.width
        );
      })
      .toBe(true);
  }

  /** Checks that the right panel's resize handle is the top element at its center. */
  async expectResizeHandleOnTop(): Promise<void> {
    const handle = this.rightPanelResizeHandle();
    await expect(handle).toBeVisible();
    await expect
      .poll(async () => {
        const box = await handle.boundingBox();
        if (!box) return null;
        return this.page.evaluate(
          ({ x, y }) => document.elementFromPoint(x, y)?.getAttribute("role"),
          { x: box.x + box.width / 2, y: box.y + box.height / 2 }
        );
      })
      .toBe("separator");
  }

  /** A tab of the right panel's tab strip, by its label. */
  rightPanelTab(label: string): Locator {
    return this.page.getByRole("tab", { name: label, exact: true });
  }

  /**
   * Opens a reply card's file in the right panel, in its own tab, and checks
   * that the preview shows the text. Escape closes the file's tab, back on
   * the Files list, then closes the panel.
   */
  async expectPublishedFilePreview(
    title: string,
    text: string,
    index = 0
  ): Promise<void> {
    await this.publishedFileCard(title, index).click();
    const preview = this.publishedFilePreview(title);
    await expect(preview).toContainText(text);
    await expect(this.rightPanelTab(title)).toHaveAttribute(
      "aria-selected",
      "true"
    );
    await expect(this.rightPanelDownload).toBeVisible();
    await expect(this.page.getByRole("dialog")).toHaveCount(0);
    await this.page.keyboard.press("Escape");
    await expect(preview).toBeHidden();
    await expect(this.publishedFilesPanelCards().first()).toBeVisible();
    await this.page.keyboard.press("Escape");
    await expect(this.publishedFilesPanel).toBeHidden();
  }

  /** Checks the Files list's text for a chat without files. */
  async expectNoPublishedFiles(): Promise<void> {
    await expect(this.rightPanelTab("Files")).toHaveAttribute(
      "aria-selected",
      "true"
    );
    await expect(
      this.publishedFilesPanel.getByText("This chat has no files yet")
    ).toBeVisible();
  }

  /**
   * The right panel's medium width in pixels, as its resize handle reports
   * it: the width it goes to, not the width drawn now.
   */
  async rightPanelWidth(): Promise<number> {
    return Number(
      await this.rightPanelResizeHandle().getAttribute("aria-valuenow")
    );
  }

  /**
   * Drags the right panel's edge toward the chat by `distance` pixels, in
   * `steps` pointer moves. A negative distance narrows the panel. A
   * `clickCount` of 2 makes the press the second click of a double click.
   */
  async dragRightPanelEdge(
    distance: number,
    { steps = 10, clickCount = 1 }: { steps?: number; clickCount?: number } = {}
  ): Promise<void> {
    const handle = this.rightPanelResizeHandle();
    const width = await this.rightPanelWidth();
    const viewport = this.page.viewportSize();
    if (!viewport) throw new Error("The page has no viewport");
    // The panel slides open: drag once its edge is in place
    await expect
      .poll(async () => (await handle.boundingBox())?.x ?? Infinity)
      .toBeLessThan(viewport.width - width + 2);
    const box = await handle.boundingBox();
    if (!box) throw new Error("The resize handle has no box");
    const y = box.y + box.height / 2;
    await this.page.mouse.move(box.x + box.width / 2, y);
    await this.page.mouse.down({ clickCount });
    await this.page.mouse.move(box.x - distance, y, { steps });
    await this.page.mouse.up({ clickCount });
  }

  async expandRightPanel(): Promise<void> {
    await this.page.getByRole("button", { name: "Expand panel" }).click();
    await this.expectRightPanelExpanded(true);
  }

  /** Checks whether the right panel fills the workspace. */
  async expectRightPanelExpanded(expanded: boolean): Promise<void> {
    await expect(
      this.page.getByRole("button", {
        name: expanded ? "Restore panel" : "Expand panel",
      })
    ).toBeVisible();
  }

  /**
   * Waits until the right panel's drawn box is `width` pixels wide (within the
   * handle's rounding), or as wide as the workspace row.
   */
  async expectRightPanelSettled(width: number | "row"): Promise<void> {
    await expect
      .poll(async () => {
        const [frame] = await this.rightPanelFrames(async () => {}, true);
        return Math.abs(
          frame!.width -
            (width === "row" ? frame!.rowEnd - frame!.rowStart : width)
        );
      })
      .toBeLessThanOrEqual(1);
  }

  /**
   * Records the right panel's box, the page's width and the row's box now,
   * then runs `action` and records them on each frame until the panel has
   * moved and then kept still for 10 frames. With `once`, records only the
   * frame before the action.
   */
  async rightPanelFrames(
    action: () => Promise<void>,
    once = false
  ): Promise<PanelFrame[]> {
    await this.page.evaluate((once) => {
      const panel = document.querySelector(
        'aside[aria-label="Files"]'
      )?.parentElement;
      // The panel's reserve, the app chrome's right panel slot, its row
      const row = panel?.parentElement?.parentElement?.parentElement;
      const pageColumn = document.querySelector("[data-app-page]");
      if (!panel || !row || !pageColumn)
        throw new Error("The panel is not mounted");
      const stillFrames = 10;
      // About 10 seconds: a panel that never moves stops recording
      const maxFrames = 600;
      const recorder = window as unknown as {
        panelFrames: PanelFrame[];
        panelSettled: boolean;
      };
      recorder.panelFrames = [];
      recorder.panelSettled = false;
      const sameBox = (a: PanelFrame, b: PanelFrame) =>
        a.start === b.start &&
        a.end === b.end &&
        a.pageWidth === b.pageWidth &&
        a.rowStart === b.rowStart &&
        a.rowEnd === b.rowEnd;
      const record = () => {
        const box = panel.getBoundingClientRect();
        const rowBox = row.getBoundingClientRect();
        const frames = recorder.panelFrames;
        frames.push({
          start: Math.round(box.left),
          end: Math.round(box.right),
          width: Math.round(box.width),
          pageWidth: Math.round(pageColumn.getBoundingClientRect().width),
          rowStart: Math.round(rowBox.left),
          rowEnd: Math.round(rowBox.right),
        });
        const last = frames[frames.length - 1]!;
        const moved = frames.some((frame) => !sameBox(frame, frames[0]!));
        const still =
          frames.length > stillFrames &&
          frames.slice(-stillFrames).every((frame) => sameBox(frame, last));
        if (once || (moved && still) || frames.length >= maxFrames) {
          recorder.panelSettled = true;
          return;
        }
        requestAnimationFrame(record);
      };
      // The first frame is the box before the action
      record();
    }, once);
    await action();
    await expect
      .poll(
        () =>
          this.page.evaluate(
            () => (window as unknown as { panelSettled: boolean }).panelSettled
          ),
        { timeout: 20000 }
      )
      .toBe(true);
    return this.page.evaluate(
      () => (window as unknown as { panelFrames: PanelFrame[] }).panelFrames
    );
  }

  private rightPanelResizeHandle(): Locator {
    return this.page.getByRole("separator", { name: "Resize panel" });
  }

  /** The tiles of the right panel's Files list, from the top. */
  publishedFilesPanelCards(): Locator {
    return this.publishedFilesPanel.getByRole("button", { name: /^Open / });
  }

  /** Checks a tile of the Files list: the name it shows. */
  async expectPublishedFilesPanelFile(
    index: number,
    { text }: { text: string }
  ): Promise<void> {
    await expect(this.publishedFilesPanelCards().nth(index)).toContainText(
      text
    );
  }

  /** Checks that a Files tile shows its document's published thumbnail. */
  async expectPublishedFilesPanelThumbnail(
    title: string,
    thumbnailFileId: string
  ): Promise<void> {
    const image = this.publishedFilesPanel
      .getByRole("button", { name: `Open ${title}` })
      .locator("img");
    await expect(image).toHaveAttribute(
      "src",
      `/api/chat/file/${thumbnailFileId}`
    );
    await expect
      .poll(() =>
        image.evaluate((element: HTMLImageElement) => element.naturalWidth)
      )
      .toBeGreaterThan(0);
  }

  /**
   * Opens a Files tile's preview in its own tab, checks its text, and closes
   * the file with Escape, back on the tile.
   */
  async expectPublishedFilesPanelPreview(
    index: number,
    title: string,
    text: string
  ): Promise<void> {
    await this.publishedFilesPanelCards().nth(index).click();
    const preview = this.publishedFilePreview(title);
    await expect(preview).toContainText(text);
    await this.page.keyboard.press("Escape");
    await expect(preview).toBeHidden();
    await expect(this.publishedFilesPanelCards().nth(index)).toBeFocused();
  }

  answerText(text: string, index = 0): Locator {
    return this.aiMessage(index).getByText(text, { exact: true });
  }

  /** With `skills`, also waits until the composer has the user's chat
   * skills, so that `@` opens the picker at once. */
  async goto(sessionId?: string, { skills = false } = {}): Promise<void> {
    await this.page.goto(sessionId ? `/app?chatId=${sessionId}` : "/app");
    await this.inputBar.textbox.waitFor({ state: "visible", timeout: 15000 });
    if (skills) await this.waitForChatSkills();
  }

  /** Opens a new chat with an agent and waits until the chat uses it. A
   * message sent sooner goes to the default agent. */
  async gotoAgent(agentId: number, name: string): Promise<void> {
    await this.page.goto(`/app?agentId=${agentId}`);
    await expect(this.page.getByTestId("agent-name-display")).toContainText(
      name
    );
  }

  /** With `skills`, also waits until the composer has the user's chat
   * skills, so that `@` opens the picker at once. */
  async reload({ skills = false } = {}): Promise<void> {
    await this.page.reload();
    await this.inputBar.textbox.waitFor({ state: "visible", timeout: 15000 });
    if (skills) await this.waitForChatSkills();
  }

  /** The picker reads the skills only on input, so `@` is typed again until
   * it opens. The input is left empty. */
  private async waitForChatSkills(): Promise<void> {
    await expect(async () => {
      await this.inputBar.clear();
      await this.inputBar.typeText("@");
      await expect(this.inputBar.skillPicker).toBeVisible({ timeout: 1000 });
    }).toPass({ timeout: 15000 });
    await this.inputBar.clear();
    await expect(this.inputBar.skillPicker).toBeHidden();
    await expect(this.inputBar.textbox).toHaveText("");
  }

  /** Waits until the chat is placed at its opening position and shown. */
  async waitForScrollReady(): Promise<void> {
    await this.page.locator('[data-scroll-ready="true"]').waitFor();
  }

  /** The latest user message's top, relative to the scroll container's. */
  async latestHumanMessageOffset(): Promise<number> {
    const container = await this.scrollContainer.boundingBox();
    const message = await this.humanMessages.last().boundingBox();
    if (!container || !message) return Number.POSITIVE_INFINITY;
    return message.y - container.y;
  }

  async scrollTo(position: "top" | "bottom"): Promise<void> {
    await this.scrollContainer.evaluate(async (el, pos) => {
      // The chat treats an upward scroll as the user's only after input.
      el.dispatchEvent(new WheelEvent("wheel"));
      el.scrollTo({ top: pos === "top" ? 0 : el.scrollHeight });
      await new Promise<void>((r) => requestAnimationFrame(() => r()));
    }, position);
  }

  async screenshotContainer(name: string): Promise<void> {
    await expect(this.container).toBeVisible();
    if ((await this.scrollContainer.count()) > 0) {
      await this.scrollTo("bottom");
    }
    await expectElementScreenshot(this.container, { name });
  }

  /**
   * Captures two screenshots of the chat container for long-content tests:
   * one scrolled to the top and one scrolled to the bottom. Ensures
   * consistent scroll positions regardless of whether the page was just
   * navigated to (top) or just finished streaming (bottom).
   */
  async screenshotContainerTopAndBottom(name: string): Promise<void> {
    await expect(this.container).toBeVisible();

    await this.scrollTo("top");
    await expectElementScreenshot(this.container, { name: `${name}-top` });

    await this.scrollTo("bottom");
    await expectElementScreenshot(this.container, { name: `${name}-bottom` });
  }

  // ---------------------------------------------------------------------------
  // Message assertions
  // ---------------------------------------------------------------------------

  async expectAnswerParagraph(text: string): Promise<void> {
    await expect(
      this.scrollContainer.getByText(text, { exact: true })
    ).toHaveCount(1);
  }

  async expectAnswerHeading(text: string): Promise<void> {
    await expect(
      this.scrollContainer.getByRole("heading", { name: text, exact: true })
    ).toHaveCount(1);
  }

  async expectAnswerTable(headers: string[], rows: number): Promise<void> {
    const table = this.aiMessage().getByRole("table");
    await expect(table.getByRole("columnheader")).toHaveText(headers);
    await expect(table.getByRole("row")).toHaveCount(rows);
  }

  /**
   * Where answer table `index` sits: whether its scroll container (the
   * table's parent) overflows, whether that container stays inside the
   * answer, and whether the table's last cell wraps onto several lines.
   */
  private answerTableLayout(index: number) {
    return this.aiMessage()
      .getByRole("table")
      .nth(index)
      .evaluate((table) => {
        const scroller = table.parentElement!;
        const answer = table.closest("[data-testid='onyx-ai-message']")!;
        const cell = table.querySelector("tbody td:last-child")!;
        return {
          overflows: scroller.scrollWidth > scroller.clientWidth,
          insideAnswer:
            scroller.getBoundingClientRect().right <=
            answer.getBoundingClientRect().right,
          cellWraps:
            cell.getBoundingClientRect().height >
            parseFloat(getComputedStyle(cell).lineHeight) * 1.5,
        };
      });
  }

  /** The table fits the answer column, and its last cell wraps. */
  async expectAnswerTableWraps(index: number): Promise<void> {
    await expect
      .poll(() => this.answerTableLayout(index))
      .toEqual({ overflows: false, insideAnswer: true, cellWraps: true });
  }

  /** The table scrolls sideways inside the answer instead of widening it. */
  async expectAnswerTableScrolls(index: number): Promise<void> {
    await expect
      .poll(() => this.answerTableLayout(index))
      .toMatchObject({ overflows: true, insideAnswer: true });
  }

  /** Hovers the answer table and clicks its copy button. */
  async copyAnswerTable(): Promise<void> {
    const message = this.aiMessage();
    await message.locator(".markdown-table-card").hover();
    await message.getByTestId("markdown-table-copy-button").click();
  }

  /** Needs the clipboard-read permission. */
  async expectClipboardText(text: string): Promise<void> {
    await expect
      .poll(() => this.page.evaluate(() => navigator.clipboard.readText()))
      .toBe(text);
  }

  async expectAnswerListItem(text: string): Promise<void> {
    await expect(
      this.aiMessage().getByRole("listitem").filter({ hasText: text })
    ).toHaveCount(1);
  }

  async copyAnswerHtml(): Promise<string> {
    // Capture the clipboard boundary without depending on the host clipboard.
    await this.page.evaluate(() => {
      sessionStorage.removeItem("test:copied-answer");
      navigator.clipboard.write = async (items) => {
        const [item] = items;
        if (!item) throw new Error("Answer was not copied");
        sessionStorage.setItem(
          "test:copied-answer",
          await (await item.getType("text/html")).text()
        );
      };
    });
    await this.aiMessage().getByTestId("AgentMessage/copy-button").click();
    let html = "";
    await expect
      .poll(async () => {
        html = await this.page.evaluate(
          () => sessionStorage.getItem("test:copied-answer") || ""
        );
        return html;
      })
      .not.toBe("");
    return html;
  }

  async expectCopyButton(): Promise<void> {
    await expect(
      this.aiMessage().getByTestId("AgentMessage/copy-button")
    ).toBeVisible();
  }

  async expectAnswerCode(text: string): Promise<void> {
    await expect(this.aiMessage().getByRole("code")).toContainText(text);
  }

  /** Inline citations must fit the text line: no taller than its line height. */
  async expectInlineCitationsFitLine(count: number): Promise<void> {
    const citations = this.aiMessage().locator("p button");
    await expect(citations).toHaveCount(count);
    for (const citation of await citations.all()) {
      await expect
        .poll(() =>
          citation.evaluate((el) => {
            const paragraph = el.closest("p");
            if (!paragraph) return false;
            const lineHeight = parseFloat(
              getComputedStyle(paragraph).lineHeight
            );
            return el.getBoundingClientRect().height <= lineHeight;
          })
        )
        .toBe(true);
    }
  }

  /**
   * Checks a failed answer at message row `row`: it keeps its partial text and
   * shows an error banner, with Regenerate only while it is the latest answer.
   */
  async expectFailedAnswer(
    row: number,
    partialText: string,
    canRegenerate: boolean
  ): Promise<void> {
    const failedRow = this.messageRows.nth(row);
    await expect(failedRow).toContainText(partialText);
    await expect(failedRow.getByTestId("chat-error-banner")).toBeVisible();
    await expect(
      failedRow.getByRole("button", { name: "Regenerate", exact: true })
    ).toHaveCount(canRegenerate ? 1 : 0);
  }

  async expectRowText(row: number, text: string): Promise<void> {
    await expect(this.messageRows.nth(row)).toContainText(text);
  }

  async expectAnswerAbsent(text: string): Promise<void> {
    await expect(this.scrollContainer).not.toContainText(text);
  }

  /** Waits for the reply to the latest message to finish. */
  async expectLatestReplyComplete(timeout = 30000): Promise<void> {
    // The latest turn is always mounted, whatever the chat's length. A
    // multi-model turn holds several replies; any complete one will do.
    await expect(
      this.messageRows.last().getByTestId("onyx-ai-message").first()
    ).toBeVisible({ timeout });
    // Text sent before the turn settles joins it as pending input.
    await this.inputBar.expectIdle(timeout);
  }

  /**
   * Waits until the open chat's saved messages are these user messages, in
   * order, each with a reply. Reads the server, not the page: the page mounts
   * only the messages near the viewport.
   */
  async expectSavedTurns(userMessages: string[]): Promise<void> {
    await expect
      .poll(
        async () => {
          const chatId = new URL(this.page.url()).searchParams.get("chatId");
          if (!chatId) return null;
          const response = await this.page.request.get(
            `/api/chat/get-chat-session/${chatId}`
          );
          if (!response.ok()) return null;
          const session: { messages: SavedChatMessage[] } =
            await response.json();
          return {
            userMessages: session.messages
              .filter((message) => message.message_type === "user")
              .map((message) => message.message),
            replies: session.messages.filter(
              (message) => message.message_type === "assistant"
            ).length,
          };
        },
        { timeout: 60000 }
      )
      .toEqual({ userMessages, replies: userMessages.length });
  }

  async expectCompleteAnswers(count: number): Promise<void> {
    await expect(this.aiMessages).toHaveCount(count);
    await expect(this.inputBar.sendButton).toBeDisabled();
  }

  /** Opens the run card and checks one completed step of the tool that
   * shows `output`. The step's body is a code panel with the request and
   * the response, so the output is matched as text. */
  async expectCustomToolResult(name: string, output: string): Promise<void> {
    // A run card folds by a button named for its step count.
    const fold = this.scrollContainer
      .getByRole("button", { name: /^\d+ steps?$/ })
      .first();
    if ((await fold.getAttribute("aria-expanded")) === "false") {
      await fold.click();
    }
    const status = this.scrollContainer.getByText(`${name} completed`, {
      exact: true,
    });
    await expect(status).toBeVisible();
    await status.click();
    await expect(this.scrollContainer.getByText(output).first()).toBeVisible();
  }

  async startIncognito(): Promise<void> {
    await this.page
      .getByRole("button", { name: "Start incognito chat" })
      .click();
    await expect(this.page.getByTestId("incognito-intro")).toBeVisible();
  }

  async expectIncognito(): Promise<void> {
    await expect(this.page.getByTestId("incognito-chat-pill")).toBeVisible();
    await expect(
      this.page.getByRole("button", { name: "share-chat-button" })
    ).toHaveCount(0);
    await expect(this.page.getByTestId("AgentMessage/like-button")).toHaveCount(
      0
    );
  }

  async exitIncognito(): Promise<void> {
    await this.page
      .getByRole("button", { name: "Exit incognito chat" })
      .click();
    await expect(this.page.getByTestId("incognito-chat-pill")).toHaveCount(0);
    await this.expectNoHumanMessages();
  }

  async expectNoSessionLink(sessionId: string): Promise<void> {
    await expect(
      this.page.locator(`a[href="/app?chatId=${sessionId}"]`)
    ).toHaveCount(0);
  }

  async expectStopping(): Promise<void> {
    await expect(this.inputBar.sendButton).toBeDisabled();
    await expect(this.inputBar.sendButton).toHaveText("Stopping…");
  }

  async stop(): Promise<void> {
    await this.inputBar.expectEmpty();
    await this.inputBar.sendButton.click();
  }

  // ---------------------------------------------------------------------------
  // Model picker
  // ---------------------------------------------------------------------------

  modelPill(modelName: string): Locator {
    return this.modelPills.filter({ hasText: modelName });
  }

  async expectModelPill(modelName: string, index = 0): Promise<void> {
    await expect(this.modelPills.nth(index)).toContainText(modelName);
  }

  async expectModelPillNot(modelText: string, index = 0): Promise<void> {
    await expect(this.modelPills.nth(index)).not.toHaveText(modelText);
  }

  /** Waits for the pill to render a name before reading it. */
  async readModelPillText(index = 0): Promise<string> {
    const pill = this.modelPills.nth(index);
    await expect(pill).toHaveText(/\S/);
    return (await pill.innerText()).trim();
  }

  /** Opens the first pill's switch list, filtered by `search` when given, and returns the popover. */
  async openModelList(search?: string): Promise<Locator> {
    await this.modelPills.first().click();
    await expect(this.modelSearchInput).toBeVisible({ timeout: 10000 });
    if (search !== undefined) await this.modelSearchInput.fill(search);
    return this.modelPopover;
  }

  modelOption(modelName: string): Locator {
    return this.modelOptions.filter({ hasText: modelName });
  }

  async closeModelPicker(): Promise<void> {
    await this.page.keyboard.press("Escape");
    await expect(this.modelPopover).toBeHidden();
  }

  /** The settings button shows only while its row is hovered. */
  async openModelSettings(modelName: string): Promise<void> {
    await this.modelPill(modelName).click();
    await this.modelPopover.getByText(modelName, { exact: true }).hover();
    await this.modelPopover
      .getByRole("button", { name: `${modelName} settings`, exact: true })
      .click();
  }

  /** Picks a row of the open list, which closes it, waits for the first pill to show the row's model and returns that name. */
  async chooseModelOption(option: Locator): Promise<string> {
    // A row's first line is its model's display name, the text its pill shows.
    const modelName = (await option.innerText()).split("\n")[0]?.trim() ?? "";
    await option.click();
    await expect(this.modelPopover).toBeHidden();
    await this.expectModelPill(modelName);
    return modelName;
  }

  /** Replaces the first pill's model through its switch list and returns the pill's display name. */
  async switchModel(modelName: string): Promise<string> {
    await this.openModelList(modelName);
    return this.chooseModelOption(this.modelOption(modelName).first());
  }

  async maximizeModelTemperature(modelName: string): Promise<void> {
    await this.openModelSettings(modelName);
    await this.modelPopover.getByRole("slider").first().press("End");
    await this.page.keyboard.press("Escape");
  }

  async selectPreviousHumanMessage(index = 0): Promise<void> {
    await this.humanMessage(index)
      .getByTestId("MessageSwitcher/container")
      .getByRole("button")
      .first()
      .click();
  }

  async editHumanMessage(text: string, index = 0): Promise<void> {
    const message = this.humanMessage(index);
    await message.hover();
    await message.getByTestId("HumanMessage/edit-button").click();
    await message.getByRole("textbox").fill(text);
  }

  async submitHumanMessageEdit(index = 0): Promise<void> {
    await this.humanMessage(index)
      .getByRole("button", { name: "Submit", exact: true })
      .click();
  }

  async cancelHumanMessageEdit(index = 0): Promise<void> {
    await this.humanMessage(index)
      .getByRole("button", { name: "Cancel", exact: true })
      .click();
  }

  async expectHumanMessage(text: string, index = 0): Promise<void> {
    await expect(this.humanMessage(index)).toContainText(text);
  }

  /** A bubble of the user's message that holds `text`, at any position. */
  async expectHumanMessageBubble(
    text: string,
    timeout?: number
  ): Promise<void> {
    await expect(
      this.humanMessageBubbles.filter({ hasText: text })
    ).toBeVisible({ timeout });
  }

  /** The skill chips of question bubble `index`, counting the bubbles of
   * messages that a running response accepted. */
  skillMentionChips(index = 0): Locator {
    return this.humanMessageBubbles
      .nth(index)
      .locator('[data-testid="mention-chip"][data-mention-type="skill"]');
  }

  async expectNoHumanMessages(): Promise<void> {
    await expect(this.humanMessages).toHaveCount(0);
  }

  async sendUntilUsageLimit(maxTurns: number): Promise<void> {
    for (
      let turn = 0;
      turn < maxTurns && !(await this.usageLimitBanner.isVisible());
      turn++
    ) {
      await this.inputBar.fill(`write a few sentences about topic ${turn}`);
      await this.inputBar.send();
      await Promise.race([
        this.usageLimitBanner
          .waitFor({ state: "visible", timeout: 45_000 })
          .catch(() => {}),
        this.aiMessage(turn)
          .waitFor({ state: "visible", timeout: 45_000 })
          .catch(() => {}),
      ]);
    }
  }

  async expectAccountUsageLimit(): Promise<void> {
    await expect(this.usageLimitBanner).toBeVisible();
    await expect(this.page.getByText(/your account/i)).toBeVisible();
  }
}
