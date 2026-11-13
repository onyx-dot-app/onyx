import { test, expect } from "@tests/e2e/chat/fixtures";
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
  test.beforeEach(() => {
    resetTurnCounter();
  });

  for (const end of [
    "wait",
    "response_end",
  ] satisfies CodeModeCellStreamOptions["end"][]) {
    test(`a program's tool call reads as a direct call (${end})`, async ({
      page,
      chatPage,
    }) => {
      await chatPage.goto();
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
      await expect(chatPage.aiMessage()).toContainText(MESSAGE);
      await expect(chatPage.aiMessage()).toContainText("1 step");
      // The call completes only in the wait observation or in the closing
      // record that follows the answer.
      await chatPage.expectCustomToolResult(TOOL, TOOL_OUTPUT);
      await expect(chatPage.aiMessage()).not.toContainText(CODE_MODE_TEXT);
    });
  }
});
