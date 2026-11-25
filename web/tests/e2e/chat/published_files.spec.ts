import { readFileSync } from "fs";
import { join } from "path";
import type { BrowserContext, Page } from "@playwright/test";
import { test, expect } from "@tests/e2e/chat/fixtures";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { ArtifactLinkPage } from "@tests/e2e/pages/ArtifactLinkPage";
import type {
  ChatArtifactAccess,
  ChatArtifactFile,
} from "@/lib/chat/publishedFiles";
import {
  buildMockPublishFilesStream,
  MockPublishedFile,
  mockChatEndpoint,
  mockChatFilePdfPreview,
  publishFilesPackets,
  resetTurnCounter,
} from "@tests/e2e/utils/chatMock";

const REPORT_TEXT = "Revenue grew in every region.";
const FINAL_REPORT_TEXT = "Revenue grew again in the final quarter.";
const MESSAGE = "The report is ready.";

/** Version `version` of the report. */
function report(
  fileId: string,
  title: string | null,
  version = 1
): MockPublishedFile {
  return {
    fileId,
    name: "report.md",
    title,
    path: "/home/onyx/workspaces/chat/report.md",
    displayPath: "report.md",
    size: 2048,
    mimeType: "text/markdown",
    artifactId: "artifact-report",
    version,
  };
}

/** Serves `file` with `body`, so each version can show its own text. */
async function mockFile(
  page: Page,
  file: MockPublishedFile,
  body: string | Buffer = `# Q3\n\n${REPORT_TEXT}\n`
): Promise<void> {
  await page.route(`**/api/chat/file/${file.fileId}*`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: file.mimeType,
      headers: {
        "Content-Disposition": `attachment; filename="${file.name}"`,
      },
      body,
    });
  });
}

/**
 * Runs every cleanup step, also after one fails, then throws the first
 * failure.
 */
async function cleanUp(
  ...steps: (() => Promise<unknown> | undefined)[]
): Promise<void> {
  const failures: unknown[] = [];
  for (const step of steps) {
    try {
      await step();
    } catch (error) {
      failures.push(error);
    }
  }
  if (failures.length > 0) throw failures[0];
}

interface SavedMessage {
  message_id: number;
  message_type: "user" | "assistant";
  parent_message: number | null;
  latest_child_message: number | null;
  message: string;
  files: { id: string; type: string; name: string }[];
  time_sent: string;
  citations: Record<string, never>;
  context_docs: null;
  tool_call: null;
  research_type: null;
  rephrased_query: null;
  overridden_model: string;
  alternate_assistant_id: null;
  current_feedback: null;
  sub_questions: [];
  error: null;
}

function savedMessage(
  message: Pick<
    SavedMessage,
    | "message_id"
    | "message_type"
    | "parent_message"
    | "latest_child_message"
    | "message"
    | "files"
  >
): SavedMessage {
  return {
    ...message,
    time_sent: new Date().toISOString(),
    citations: {},
    context_docs: null,
    tool_call: null,
    research_type: null,
    rephrased_query: null,
    overridden_model: "",
    alternate_assistant_id: null,
    current_feedback: null,
    sub_questions: [],
    error: null,
  };
}

/**
 * Serves a saved chat of one reply, `answer`, whose replay packets publish
 * files: the route stays through a reload. `published` is the load's list of
 * the chat's files.
 */
async function routeSavedChat(
  page: Page,
  sessionId: string,
  replay: Record<string, unknown>[],
  published: MockPublishedFile[],
  answer: string = MESSAGE
): Promise<void> {
  await page.route(
    `**/api/chat/get-chat-session/${sessionId}*`,
    async (route) => {
      const response = await route.fetch();
      const saved: Record<string, unknown> = await response.json();
      await route.fulfill({
        response,
        json: {
          ...saved,
          messages: [
            savedMessage({
              message_id: 1,
              message_type: "user",
              parent_message: null,
              latest_child_message: 2,
              message: "Write the quarterly report",
              files: [],
            }),
            savedMessage({
              message_id: 2,
              message_type: "assistant",
              parent_message: 1,
              latest_child_message: null,
              message: answer,
              files: [],
            }),
          ],
          packets: [
            [
              ...replay,
              {
                placement: { turn_index: replay.length, tab_index: 0 },
                obj: {
                  type: "message_start",
                  id: "saved-answer",
                  content: answer,
                  final_documents: null,
                },
              },
              {
                placement: { turn_index: replay.length, tab_index: 0 },
                obj: { type: "stop", stop_reason: "finished" },
              },
            ],
          ],
          published_files: published.map((file) => ({
            file_id: file.fileId,
            name: file.name,
            title: file.title,
            path: file.path,
            display_path: file.displayPath,
            size: file.size,
            mime_type: file.mimeType,
            artifact_id: file.artifactId,
            version: file.version,
          })),
        },
      });
    }
  );
}

test.describe("Published files", () => {
  test.beforeEach(() => {
    resetTurnCounter();
  });

  test.afterEach(async ({ page }) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("a published file shows as a card that previews and downloads", async ({
    page,
    chatPage,
  }) => {
    const file = report("published-file-1", "Q3 report");
    await chatPage.goto();
    await mockFile(page, file);
    await mockChatEndpoint(page, buildMockPublishFilesStream([file], MESSAGE));

    await sendMessage(page, "Write the quarterly report");
    await expect(chatPage.answerText(MESSAGE)).toBeVisible();
    await expect(chatPage.publishedFileCards()).toHaveCount(1);
    await chatPage.expectPublishedFile("Q3 report", {
      fileName: file.name,
      details: /MD · 2/,
      href: `/api/chat/file/${file.fileId}`,
    });
    // The cards show once the turn ends, after its answer
    const answerBox = await chatPage.answerText(MESSAGE).boundingBox();
    const cardBox = await chatPage.publishedFileCard("Q3 report").boundingBox();
    expect(cardBox!.y).toBeGreaterThan(answerBox!.y);
    await chatPage.expectPublishedFilePreview("Q3 report", REPORT_TEXT);
  });

  test("a reply shows five cards, and a button shows all its files in the panel", async ({
    page,
    chatPage,
  }) => {
    const files = Array.from(
      { length: 6 },
      (_, index): MockPublishedFile => ({
        ...report(`published-file-cap-${index}`, `Report ${index}`),
        name: `report-${index}.md`,
        path: `/home/onyx/workspaces/chat/report-${index}.md`,
        displayPath: `report-${index}.md`,
        artifactId: `artifact-report-${index}`,
      })
    );
    await chatPage.goto();
    for (const file of files) await mockFile(page, file);
    await mockChatEndpoint(page, buildMockPublishFilesStream(files, MESSAGE));

    await sendMessage(page, "Write the reports");
    await expect(chatPage.answerText(MESSAGE)).toBeVisible();
    await expect(chatPage.publishedFileCards()).toHaveCount(5);
    await chatPage.viewAllPublishedFiles(6);
    await expect(chatPage.publishedFilesPanelCards()).toHaveCount(6);
  });

  test("a file tab shows markdown as a document, a CSV as a grid, and a PDF, a Word file and a deck as pages", async ({
    page,
    chatPage,
  }) => {
    const notes = report("published-file-10", "Q3 notes");
    const sales: MockPublishedFile = {
      ...report("published-file-11", "Q3 sales"),
      name: "sales.csv",
      path: "/home/onyx/workspaces/chat/sales.csv",
      displayPath: "sales.csv",
      artifactId: "artifact-sales",
      mimeType: "text/csv",
    };
    const pdf: MockPublishedFile = {
      ...report("published-file-12", "Q3 slides"),
      thumbnailFileId: "slides-thumbnail",
      name: "report.pdf",
      path: "/home/onyx/workspaces/chat/report.pdf",
      displayPath: "report.pdf",
      artifactId: "artifact-slides",
      mimeType: "application/pdf",
    };
    const letter: MockPublishedFile = {
      ...report("published-file-13", "Q3 letter"),
      name: "letter.docx",
      path: "/home/onyx/workspaces/chat/letter.docx",
      displayPath: "letter.docx",
      artifactId: "artifact-letter",
      mimeType:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    };
    const deck: MockPublishedFile = {
      ...report("published-file-14", "Q3 deck"),
      thumbnailFileId: "deck-thumbnail",
      name: "deck.pptx",
      path: "/home/onyx/workspaces/chat/deck.pptx",
      displayPath: "deck.pptx",
      artifactId: "artifact-deck",
      mimeType:
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    };
    await page.setViewportSize({ width: 1600, height: 900 });
    await chatPage.goto();
    await mockFile(page, notes);
    await mockFile(
      page,
      sales,
      'Region,Owner\nNorth,"Smith, Jane"\nSouth,Lee\n'
    );
    await mockFile(
      page,
      pdf,
      readFileSync(join(__dirname, "../fixtures/two_pages.pdf"))
    );
    await mockFile(
      page,
      letter,
      readFileSync(join(__dirname, "../fixtures/three_images.docx"))
    );
    await mockFile(
      page,
      deck,
      readFileSync(join(__dirname, "../fixtures/two_slides.pptx"))
    );
    await mockChatFilePdfPreview(page);
    const firstPage = readFileSync(
      join(__dirname, "../fixtures/first_page.jpg")
    );
    for (const fileId of [pdf.thumbnailFileId, deck.thumbnailFileId]) {
      await page.route(`**/api/chat/file/${fileId}*`, (route) =>
        route.fulfill({
          status: 200,
          contentType: "image/jpeg",
          body: firstPage,
        })
      );
    }
    await mockChatEndpoint(
      page,
      buildMockPublishFilesStream([notes, sales, pdf, letter, deck], MESSAGE)
    );

    await sendMessage(page, "Write the quarterly report");
    await expect(chatPage.publishedFileCards()).toHaveCount(5);
    await chatPage.expectMarkdownPreview("Q3 notes", "Q3");
    // A quoted comma stays inside its cell
    await chatPage.expectSpreadsheetPreview("Q3 sales", "Smith, Jane");
    await chatPage.expectPdfPreview("Q3 slides", 2);
    // The server converts a deck and a Word file to a PDF
    await chatPage.expectPdfPreview("Q3 deck", 2);
    await chatPage.expectPdfPreview("Q3 letter", 2);
    // The resize handle stays over the pages
    await chatPage.expectResizeHandleOnTop();

    // The Files list shows the first pages that the server drew at publish
    await chatPage.rightPanelTab("Files").click();
    await chatPage.expectPublishedFilesPanelThumbnail(
      "Q3 slides",
      "slides-thumbnail"
    );
    await chatPage.expectPublishedFilesPanelThumbnail(
      "Q3 deck",
      "deck-thumbnail"
    );
  });

  test("a JSON file tab shows the file's numbers as written", async ({
    page,
    chatPage,
  }) => {
    const data: MockPublishedFile = {
      ...report("published-file-15", "Q3 data"),
      name: "data.json",
      path: "/home/onyx/workspaces/chat/data.json",
      displayPath: "data.json",
      artifactId: "artifact-data",
      mimeType: "application/json",
    };
    await chatPage.goto();
    await mockFile(page, data, '{"id":9007199254740993,"ratio":1.0}');
    await mockChatEndpoint(page, buildMockPublishFilesStream([data], MESSAGE));

    await sendMessage(page, "Export the data");
    await chatPage.publishedFileCard("Q3 data").click();
    // Minified JSON shows indented
    const preview = chatPage.publishedFilePreview("Q3 data");
    await expect(preview).toContainText('"id": 9007199254740993,');
    await expect(preview).toContainText('"ratio": 1.0');
  });

  test("a saved reply shows a card for each publish, and the panel the newest version of each file", async ({
    page,
    chatPage,
    api,
  }) => {
    const first = report("published-file-2", "Q3 report");
    const second = report("published-file-3", null, 2);
    // Published by an answer that the paged load does not hold, such as an
    // older one or another branch's.
    const notes: MockPublishedFile = {
      ...report("published-file-6", "Meeting notes"),
      name: "notes.md",
      path: "/home/onyx/workspaces/chat/notes.md",
      displayPath: "notes.md",
      artifactId: "artifact-notes",
    };
    let sessionId: string | undefined;
    try {
      sessionId = await api.createChatSession("Published files");
      await mockFile(page, first);
      await mockFile(page, second);
      await mockFile(page, notes);
      await routeSavedChat(
        page,
        sessionId,
        [
          ...publishFilesPackets(0, [first]),
          ...publishFilesPackets(1, [second]),
        ],
        // The server lists the newest version of each file, by its first
        // publish
        [notes, second]
      );

      await chatPage.goto(sessionId);
      await expect(chatPage.answerText(MESSAGE)).toBeVisible();
      await expect(chatPage.publishedFileCards()).toHaveCount(2);
      await chatPage.expectPublishedFile("Q3 report", {
        fileName: first.name,
        details: /MD · 2/,
        href: `/api/chat/file/${first.fileId}`,
      });
      // The second version has no title, so it shows its name.
      await chatPage.expectPublishedFile(second.name, {
        fileName: second.name,
        details: /MD · 2/,
        href: `/api/chat/file/${second.fileId}`,
      });
      await chatPage.expectPublishedFilePreview(second.name, REPORT_TEXT);

      // The panel shows the newest version of each of the chat's files, also
      // of the answer that the page did not load, newest file first.
      await chatPage.rightPanelToggle.click();
      await expect(chatPage.publishedFilesPanelCards()).toHaveCount(2);
      await chatPage.expectPublishedFilesPanelFile(0, {
        text: second.name,
      });
      await chatPage.expectPublishedFilesPanelFile(1, {
        text: "Meeting notes",
      });
    } finally {
      await cleanUp(() =>
        sessionId ? api.deleteChatSession(sessionId) : undefined
      );
    }
  });

  test("a card opens its file for an agent without search when the chat lists no files", async ({
    browser,
    page,
    chatPage,
    api,
  }) => {
    // A file that the chat's list leaves out: its card shows, but the load
    // lists no files
    const file = report("published-file-9", "Q3 report");
    let adminContext: BrowserContext | undefined;
    let admin: OnyxApiClient | undefined;
    let agentId: number | undefined;
    let sessionId: string | undefined;
    try {
      adminContext = await browser.newContext({
        storageState: "admin_auth.json",
      });
      admin = new OnyxApiClient(adminContext.request);
      agentId = await admin.createAgent("Published files without search");
      sessionId = await api.createChatSession("Unlisted file", agentId);
      await mockFile(page, file);
      await routeSavedChat(page, sessionId, publishFilesPackets(0, [file]), []);
      await chatPage.goto(sessionId);
      await expect(chatPage.answerText(MESSAGE)).toBeVisible();
      await expect(chatPage.rightPanelToggle).toBeVisible();

      await chatPage.publishedFileCard("Q3 report").click();
      await expect(chatPage.publishedFilePreview("Q3 report")).toContainText(
        REPORT_TEXT
      );
    } finally {
      await cleanUp(
        () => (sessionId ? api.deleteChatSession(sessionId) : undefined),
        () => (agentId === undefined ? undefined : admin?.deleteAgent(agentId)),
        () => adminContext?.close()
      );
    }
  });

  test("the panel toggle opens a chat without files on the Files list, and closing returns focus to it", async ({
    page,
    chatPage,
    api,
  }) => {
    let sessionId: string | undefined;
    try {
      sessionId = await api.createChatSession("No published files");
      await routeSavedChat(page, sessionId, [], []);
      await chatPage.goto(sessionId);
      await expect(chatPage.answerText(MESSAGE)).toBeVisible();

      await expect(chatPage.rightPanelToggle).toHaveAttribute(
        "aria-expanded",
        "false"
      );
      // The share button keeps clear of the toggle over the header's end
      await expect
        .poll(() => chatPage.shareButtonEndGap(false))
        .toBeGreaterThanOrEqual(0);
      await chatPage.rightPanelToggle.click();
      await expect(chatPage.publishedFilesPanel).toBeVisible();
      await chatPage.expectNoPublishedFiles();
      // Beside the open panel, which holds the toggle, it keeps only the
      // header's 16px padding
      await expect
        .poll(() => chatPage.shareButtonEndGap(true))
        .toBeLessThanOrEqual(20);
      await expect
        .poll(() => chatPage.shareButtonEndGap(true))
        .toBeGreaterThanOrEqual(0);

      await chatPage.rightPanelToggle.click();
      await expect(chatPage.publishedFilesPanel).toBeHidden();
      await expect(chatPage.rightPanelToggle).toHaveAttribute(
        "aria-expanded",
        "false"
      );
      await expect(chatPage.rightPanelToggle).toBeFocused();
    } finally {
      await cleanUp(() =>
        sessionId ? api.deleteChatSession(sessionId) : undefined
      );
    }
  });

  test("the files panel shows the newest version of a file across replies and previews it", async ({
    page,
    chatPage,
  }) => {
    const first = report("published-file-4", "Q3 report");
    const second = report("published-file-5", "Q3 report, final", 2);
    const finalMessage = "The final report is ready.";
    await chatPage.goto();
    await mockFile(page, first);
    await mockFile(page, second, `# Q3\n\n${FINAL_REPORT_TEXT}\n`);

    await mockChatEndpoint(page, buildMockPublishFilesStream([first], MESSAGE));
    await sendMessage(page, "Write the quarterly report");
    await expect(chatPage.answerText(MESSAGE)).toBeVisible();
    // The newest version's card opens a tab that follows the newest version
    await chatPage.publishedFileCard("Q3 report").click();
    await expect(chatPage.publishedFilePreview("Q3 report")).toContainText(
      REPORT_TEXT
    );

    await mockChatEndpoint(
      page,
      buildMockPublishFilesStream([second], finalMessage)
    );
    await sendMessage(page, "Finalize the report");
    await expect(chatPage.answerText(finalMessage, 1)).toBeVisible();

    // The open tab moves to the new version and shows its text
    const finalPreview = chatPage.publishedFilePreview("Q3 report, final");
    await expect(finalPreview).toContainText(FINAL_REPORT_TEXT);
    await expect(finalPreview).not.toContainText(REPORT_TEXT);

    // Both replies published one file: the Files list shows only the newest
    // version.
    await chatPage.rightPanelTab("Files").click();
    await expect(chatPage.publishedFilesPanelCards()).toHaveCount(1);
    await chatPage.expectPublishedFilesPanelFile(0, {
      text: "Q3 report, final",
    });
    await chatPage.expectPublishedFilesPanelPreview(
      0,
      "Q3 report, final",
      FINAL_REPORT_TEXT
    );

    await chatPage.rightPanelToggle.click();
    await expect(chatPage.publishedFilesPanel).toBeHidden();
  });

  test("the panel keeps its tabs and width, and Escape leaves full screen, then closes tabs, then the panel", async ({
    page,
    chatPage,
    api,
  }) => {
    const reportFile = report("published-file-7", "Q3 report");
    const notes: MockPublishedFile = {
      ...report("published-file-8", "Meeting notes"),
      name: "notes.md",
      path: "/home/onyx/workspaces/chat/notes.md",
      displayPath: "notes.md",
      artifactId: "artifact-notes",
    };
    await page.setViewportSize({ width: 1600, height: 900 });
    let sessionId: string | undefined;
    try {
      sessionId = await api.createChatSession("Published files panel");
      await mockFile(page, reportFile);
      await mockFile(page, notes);
      await routeSavedChat(
        page,
        sessionId,
        publishFilesPackets(0, [reportFile, notes]),
        [reportFile, notes]
      );
      await chatPage.goto(sessionId);
      await expect(chatPage.answerText(MESSAGE)).toBeVisible();

      // Two previews open in their own tabs.
      await chatPage.publishedFileCard("Q3 report").click();
      await expect(chatPage.publishedFilePreview("Q3 report")).toContainText(
        REPORT_TEXT
      );
      await chatPage.publishedFileCard("Meeting notes").click();
      await expect(
        chatPage.publishedFilePreview("Meeting notes")
      ).toContainText(REPORT_TEXT);

      // Closing and reopening the panel keeps the tabs.
      await chatPage.rightPanelToggle.click();
      await expect(chatPage.publishedFilesPanel).toBeHidden();
      await chatPage.rightPanelToggle.click();
      await expect(chatPage.rightPanelTab("Q3 report")).toBeVisible();
      await expect(chatPage.rightPanelTab("Meeting notes")).toHaveAttribute(
        "aria-selected",
        "true"
      );

      // A mouse drag of the edge widens the panel.
      const before = await chatPage.rightPanelWidth();
      await chatPage.dragRightPanelEdge(200);
      await expect
        .poll(() => chatPage.rightPanelWidth())
        .toBeGreaterThan(before + 150);
      // A fast second drag keeps its width: one move, a release before the
      // next frame, and the system counts the press as a double click.
      const dragged = await chatPage.rightPanelWidth();
      await chatPage.dragRightPanelEdge(-150, { steps: 1, clickCount: 2 });
      await expect
        .poll(async () =>
          Math.abs((await chatPage.rightPanelWidth()) - (dragged - 150))
        )
        .toBeLessThanOrEqual(1);
      const width = await chatPage.rightPanelWidth();

      // The chat keeps the width through a reload.
      await chatPage.reload();
      await expect(chatPage.answerText(MESSAGE)).toBeVisible();
      await chatPage.publishedFileCard("Q3 report").click();
      await chatPage.publishedFileCard("Meeting notes").click();
      await expect(
        chatPage.publishedFilePreview("Meeting notes")
      ).toContainText(REPORT_TEXT);
      await expect.poll(() => chatPage.rightPanelWidth()).toBe(width);

      // At full size the panel covers the row: a wider window shows no
      // frame of the page beside it.
      await chatPage.expectRightPanelSettled(width);
      await chatPage.expandRightPanel();
      await chatPage.expectRightPanelSettled("row");
      const grown = await chatPage.rightPanelFrames(() =>
        page.setViewportSize({ width: 1900, height: 900 })
      );
      expect(grown[grown.length - 1]!.rowEnd).toBeGreaterThan(grown[0]!.rowEnd);
      grown.forEach((frame) => {
        expect(frame.start).toBeLessThanOrEqual(frame.rowStart);
        expect(frame.end).toBeGreaterThanOrEqual(frame.rowEnd);
      });

      // Escape leaves full screen: the panel shrinks to its medium width at
      // the workspace's end, and the page beside it stays still. Then Escape
      // closes each file's tab, then the panel.
      await chatPage.expectRightPanelSettled("row");
      const frames = await chatPage.rightPanelFrames(() =>
        page.keyboard.press("Escape")
      );
      await chatPage.expectRightPanelExpanded(false);
      // The handle hides at full size
      const medium = await chatPage.rightPanelWidth();
      const [first, last] = [frames[0]!, frames[frames.length - 1]!];
      expect(first.width).toBe(first.rowEnd - first.rowStart);
      // The handle reports the width rounded
      expect(Math.abs(last.width - medium)).toBeLessThanOrEqual(1);
      // The panel draws frames between the two widths
      expect(
        frames.some(
          (frame) => frame.width < first.width - 1 && frame.width > medium + 1
        )
      ).toBe(true);
      expect(first.pageWidth).toBeGreaterThan(0);
      frames.forEach((frame, index) => {
        expect(frame.end).toBe(first.end);
        expect(frame.pageWidth).toBe(first.pageWidth);
        expect(frame.width).toBeGreaterThanOrEqual(medium - 1);
        expect(frame.width).toBeLessThanOrEqual(
          index === 0 ? first.width : frames[index - 1]!.width
        );
      });
      await expect(chatPage.rightPanelTab("Meeting notes")).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(chatPage.rightPanelTab("Meeting notes")).toBeHidden();
      await expect(chatPage.rightPanelTab("Q3 report")).toHaveAttribute(
        "aria-selected",
        "true"
      );
      await page.keyboard.press("Escape");
      await expect(chatPage.rightPanelTab("Q3 report")).toBeHidden();
      await expect(chatPage.publishedFilesPanel).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(chatPage.publishedFilesPanel).toBeHidden();
    } finally {
      await cleanUp(() =>
        sessionId ? api.deleteChatSession(sessionId) : undefined
      );
    }
  });
});

test.describe("Published file tabs on a touch screen", () => {
  test.use({ hasTouch: true });

  test.beforeEach(() => {
    resetTurnCounter();
  });

  test.afterEach(async ({ page }) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("a swipe scrolls the tab strip, and a press and hold or a mouse drag moves a tab", async ({
    page,
    chatPage,
  }) => {
    const files = Array.from(
      { length: 5 },
      (_, index): MockPublishedFile => ({
        ...report(`published-file-touch-${index}`, `Quarterly report ${index}`),
        name: `report-${index}.md`,
        path: `/home/onyx/workspaces/chat/report-${index}.md`,
        displayPath: `report-${index}.md`,
        artifactId: `artifact-report-touch-${index}`,
      })
    );
    const titles = files.map((file) => file.title ?? file.name);
    await chatPage.goto();
    for (const file of files) await mockFile(page, file);
    await mockChatEndpoint(page, buildMockPublishFilesStream(files, MESSAGE));
    await sendMessage(page, "Write the reports");
    for (const title of titles) {
      await chatPage.publishedFileCard(title).click();
      await expect(chatPage.publishedFilePreview(title)).toContainText(
        REPORT_TEXT
      );
    }
    const order = ["Files", ...titles];
    await chatPage.expectRightPanelTabs(order);
    // At 560 px the panel cannot fit the tabs (112 px each at the least), and
    // the drags below stay clear of the strip's edges, where a drag scrolls it
    await chatPage.dragRightPanelEdge(560 - (await chatPage.rightPanelWidth()));

    // A swipe scrolls the strip and moves no tab
    await chatPage.swipeRightPanelTabs(-150);
    await expect
      .poll(() => chatPage.rightPanelTabsScrollLeft())
      .toBeGreaterThan(0);
    await chatPage.expectRightPanelTabs(order);
    // The strip holds more than one swipe, and a swipe carries on after the
    // finger lifts, so swipes back until it is at its start
    await expect
      .poll(async () => {
        await chatPage.swipeRightPanelTabs(150);
        return chatPage.rightPanelTabsScrollLeft();
      })
      .toBe(0);
    await chatPage.expectRightPanelTabs(order);

    await chatPage.holdAndDragRightPanelTab(titles[0]!, titles[1]!);
    await chatPage.expectRightPanelTabs([
      "Files",
      titles[1]!,
      titles[0]!,
      ...titles.slice(2),
    ]);

    await chatPage.mouseDragRightPanelTab(titles[0]!, titles[1]!);
    await chatPage.expectRightPanelTabs(order);
  });
});

test.describe("Artifact links", () => {
  // An artifact of another chat, as the artifact tools link it
  const ARTIFACT_ID = "5b1f6e2a-7c3d-4e8f-9a0b-1c2d3e4f5a6b";
  const file: MockPublishedFile = {
    ...report("artifact-link-file", "Q3 report"),
    artifactId: ARTIFACT_ID,
  };
  const LINK = `/app/artifacts/${ARTIFACT_ID}/v1`;

  /**
   * Serves the artifact's metadata as the chat `chatId`'s, with the user's
   * `access`, in the route's response type.
   */
  async function mockArtifact(
    page: Page,
    chatId: string,
    access: ChatArtifactAccess = "owner"
  ): Promise<void> {
    const body: ChatArtifactFile = {
      file_id: file.fileId,
      name: file.name,
      title: file.title,
      path: file.path,
      display_path: file.displayPath,
      size: file.size,
      mime_type: file.mimeType,
      artifact_id: file.artifactId,
      version: file.version,
      thumbnail_file_id: null,
      chat_id: chatId,
      access,
    };
    await page.route(`**/api/chat/artifacts/${ARTIFACT_ID}*`, (route) =>
      route.fulfill({ status: 200, json: body })
    );
  }

  test.afterEach(async ({ page }) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("a link in a reply opens another chat's file in this chat's panel", async ({
    page,
    chatPage,
    api,
  }) => {
    let sessionId: string | undefined;
    try {
      sessionId = await api.createChatSession("Artifact link");
      await mockFile(page, file);
      await mockArtifact(page, "another-chat");
      await routeSavedChat(
        page,
        sessionId,
        [],
        [],
        `See [the report](${LINK}).`
      );
      await chatPage.goto(sessionId);

      await chatPage.clickArtifactLink("the report");
      await expect(chatPage.publishedFilePreview("Q3 report")).toContainText(
        REPORT_TEXT
      );
      await expect(chatPage.rightPanelTab("Q3 report")).toHaveAttribute(
        "aria-selected",
        "true"
      );
      // The click opened the panel, not the link.
      expect(new URL(page.url()).searchParams.get("chatId")).toBe(sessionId);
      await expect(page).toHaveURL(/\/app\?chatId=/);
    } finally {
      await cleanUp(() =>
        sessionId ? api.deleteChatSession(sessionId) : undefined
      );
    }
  });

  test("an opened link lands in its chat with the panel on the file", async ({
    page,
    chatPage,
    api,
  }) => {
    let sessionId: string | undefined;
    try {
      sessionId = await api.createChatSession("Artifact owner");
      await mockFile(page, file);
      await mockArtifact(page, sessionId);
      await routeSavedChat(page, sessionId, [], [file]);

      await new ArtifactLinkPage(page).goto(LINK);
      await expect(chatPage.publishedFilePreview("Q3 report")).toContainText(
        REPORT_TEXT
      );
      await expect(chatPage.answerText(MESSAGE)).toBeVisible();
      // The chat drops the link's parameters once it opened the file.
      await expect
        .poll(() => new URL(page.url()).search)
        .toBe(`?chatId=${sessionId}`);
    } finally {
      await cleanUp(() =>
        sessionId ? api.deleteChatSession(sessionId) : undefined
      );
    }
  });

  test("an opened link of a publicly shared chat lands a reader in its shared view with the panel on the file", async ({
    browser,
    page,
    chatPage,
  }) => {
    let ownerContext: BrowserContext | undefined;
    let owner: OnyxApiClient | undefined;
    let sessionId: string | undefined;
    try {
      // Another user's chat, shared with everyone
      ownerContext = await browser.newContext({
        storageState: "admin_auth.json",
      });
      owner = new OnyxApiClient(ownerContext.request);
      const ownerPage = await ownerContext.newPage();
      await new ChatPage(ownerPage).goto();
      await sendMessage(ownerPage, "Write the quarterly report");
      sessionId =
        new URL(ownerPage.url()).searchParams.get("chatId") ?? undefined;
      if (!sessionId) throw new Error("The owner's chat has no ID");
      const shared = await ownerContext.request.patch(
        `/api/chat/chat-session/${sessionId}`,
        { data: { sharing_status: "public" } }
      );
      expect(shared.ok()).toBe(true);
      await mockFile(page, file);
      await mockArtifact(page, sessionId, "chat_reader");

      await new ArtifactLinkPage(page).goto(LINK);
      await expect(chatPage.publishedFilePreview("Q3 report")).toContainText(
        REPORT_TEXT
      );
      // The shared view drops the link's parameters once it opened the file.
      await expect
        .poll(() => {
          const url = new URL(page.url());
          return `${url.pathname}${url.search}`;
        })
        .toBe(`/app/shared/${sessionId}`);
    } finally {
      await cleanUp(
        () => (sessionId ? owner?.deleteChatSession(sessionId) : undefined),
        () => ownerContext?.close()
      );
    }
  });

  test("an opened link that the user may open only as a file shows the file alone", async ({
    page,
  }) => {
    const linkPage = new ArtifactLinkPage(page);
    await mockFile(page, file);
    await mockArtifact(page, "a-chat-of-another-user", "file_only");

    expect(await linkPage.goto(LINK)).toBe(200);
    await expect(linkPage.filePreview("Q3 report")).toContainText(REPORT_TEXT);
    await expect(linkPage.download).toHaveAttribute("download", file.name);
    // No chat opens: the page stays on the link.
    await expect(page).toHaveURL((url) => url.pathname === LINK);
  });

  test("another user gets not-found from a link", async ({ page }) => {
    const linkPage = new ArtifactLinkPage(page);
    // The real route: no artifact of this ID is the user's to open.
    expect(await linkPage.goto(LINK)).toBe(404);
    await linkPage.expectNotFound(LINK, "Q3 report");
  });
});
