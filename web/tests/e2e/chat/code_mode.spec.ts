import { expect, test } from "@playwright/test";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import {
  buildMockCodeModeCellStream,
  CodeModeCellStreamOptions,
  mockChatEndpoint,
  resetTurnCounter,
} from "@tests/e2e/utils/chatMock";

const TOOL = "lookup_orders";
const TOOL_OUTPUT = "3 orders";
const MESSAGE = "You have three open orders.";
// Code mode runs behind the scenes; none of it is user-facing copy.
const CODE_MODE_TEXT =
  /program output|await lookup_orders|\bcell\b|Ran code|continues|execute_code|wait_code/i;

test.describe("Code mode", () => {
  let chat: ChatPage;

  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    chat = new ChatPage(page);
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
  });

  for (const end of [
    "wait",
    "response_end",
  ] satisfies CodeModeCellStreamOptions["end"][]) {
    test(`a program's tool call reads as a direct call (${end})`, async ({
      page,
    }) => {
      await chat.goto();
      await mockChatEndpoint(
        page,
        buildMockCodeModeCellStream({
          code: "orders = await lookup_orders()\nprint('program output')",
          toolName: TOOL,
          toolOutput: TOOL_OUTPUT,
          message: MESSAGE,
          end,
        })
      );

      await sendMessage(page, "How many orders are open?");
      await expect(chat.aiMessage()).toContainText(MESSAGE);
      await expect(chat.aiMessage()).toContainText("1 step");
      // The call completes only in the wait observation or in the closing
      // record that follows the answer.
      await chat.expectCustomToolResult(TOOL, TOOL_OUTPUT);
      await expect(chat.aiMessage()).not.toContainText(CODE_MODE_TEXT);
    });
  }
});
