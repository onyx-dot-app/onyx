import type { Page } from "@playwright/test";
import { test, expect } from "@tests/e2e/chat/fixtures";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import {
  buildMockPublishFilesStream,
  MockPublishedFile,
  mockChatEndpoint,
  mockChatNotification,
  publishFilesPackets,
  resetTurnCounter,
} from "@tests/e2e/utils/chatMock";

const REPORT_TEXT = "Revenue grew in every region.";
const MESSAGE = "The report is ready.";

function report(fileId: string, title: string | null): MockPublishedFile {
  return {
    fileId,
    name: "report.md",
    title,
    path: "/home/onyx/workspaces/chat/report.md",
    size: 2048,
    mimeType: "text/markdown",
  };
}

async function mockFile(page: Page, file: MockPublishedFile): Promise<void> {
  await page.route(`**/api/chat/file/${file.fileId}*`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: file.mimeType,
      headers: {
        "Content-Disposition": `attachment; filename="${file.name}"`,
      },
      body: `# Q3\n\n${REPORT_TEXT}\n`,
    });
  });
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
    await chatPage.expectPublishedFilePreview("Q3 report", REPORT_TEXT);
  });

  test("a saved reply shows each version of a republished file", async ({
    page,
    chatPage,
    api,
  }) => {
    const first = report("published-file-2", "Q3 report");
    const second = report("published-file-3", null);
    const sessionId = await api.createChatSession("Published files");
    try {
      await mockFile(page, first);
      await mockFile(page, second);
      const replay = [
        ...publishFilesPackets(0, [first]),
        ...publishFilesPackets(1, [second]),
        {
          placement: { turn_index: 2, tab_index: 0 },
          obj: {
            type: "message_start",
            id: "saved-answer",
            content: MESSAGE,
            final_documents: null,
          },
        },
        {
          placement: { turn_index: 2, tab_index: 0 },
          obj: { type: "stop", stop_reason: "finished" },
        },
      ];
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
                  message: MESSAGE,
                  files: [first, second].map((file) => ({
                    id: file.fileId,
                    type: "document",
                    name: file.name,
                  })),
                }),
              ],
              packets: [
                replay.map((packet) => mockChatNotification(packet, sessionId)),
              ],
            },
          });
        }
      );

      await chatPage.goto(sessionId);
      await expect(chatPage.answerText(MESSAGE)).toBeVisible();
      await expect(chatPage.publishedFileCards()).toHaveCount(2);
      await chatPage.expectPublishedFile("Q3 report", {
        fileName: first.name,
        details: /MD · 2/,
        href: `/api/chat/file/${first.fileId}`,
      });
      // The second publish of the path has no title, so it shows its name.
      await chatPage.expectPublishedFile(second.name, {
        fileName: second.name,
        details: /Updated version · MD · 2/,
        href: `/api/chat/file/${second.fileId}`,
      });
      await chatPage.expectPublishedFilePreview(second.name, REPORT_TEXT);
    } finally {
      await api.deleteChatSession(sessionId);
    }
  });
});
