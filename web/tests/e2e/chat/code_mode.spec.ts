import { test, expect } from "@tests/e2e/chat/fixtures";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import {
  buildMockCodeModeCellStream,
  CodeModeCellStreamOptions,
  mockChatEndpoint,
  resetTurnCounter,
} from "@tests/e2e/utils/chatMock";
import {
  addMockLlmConversation,
  CODE_MODE_ENABLED,
  mockLlmNonce,
  MOCK_LLM_BACKEND_URL,
} from "@tests/e2e/utils/mockLlm";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const TOOL = "lookup_orders";
const TOOL_OUTPUT = "3 orders";
const MESSAGE = "You have three open orders.";
// Code mode runs behind the scenes; none of it is user-facing copy.
const CODE_MODE_TEXT =
  /program output|await \w+\(|\bcell\b|Ran code|continues|execute_code|wait_code/i;

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

  test("a program's custom tool call runs and survives a history reload @code-mode", async ({
    browser,
    page,
    chatPage,
    api,
  }) => {
    test.skip(
      !CODE_MODE_ENABLED,
      "Needs a backend with CODE_MODE_ENABLED=true"
    );
    const admin = await browser.newContext({ storageState: "admin_auth.json" });
    const adminApi = new OnyxApiClient(admin.request);
    const nonce = mockLlmNonce();
    const operation = "check_service_health";
    const toolId = await adminApi.createCustomTool(
      `Health ${nonce}`,
      "Read service health",
      {
        baseUrl: MOCK_LLM_BACKEND_URL,
        path: "/health",
        operationId: operation,
      }
    );
    let agentId: number | undefined;
    let sessionId: string | undefined;
    try {
      const me = await page.request.get("/api/me");
      expect(me.ok()).toBe(true);
      const user: { id: string } = await me.json();
      agentId = await adminApi.createAgentWithMcpTools(
        `Code mode ${nonce}`,
        [toolId],
        { userIds: [user.id] }
      );
      sessionId = await api.createChatSession("Code mode", agentId);
      const callId = `call-${nonce}`;
      const answer = "The program read the service health.";
      await addMockLlmConversation({
        name: nonce,
        conditions: { prompt_contains: [nonce] },
        replies: [
          {
            tool_calls: [
              {
                id: callId,
                name: "execute_code",
                arguments: {
                  code: `health = await ${operation}()\nprint('program output', health)`,
                },
              },
            ],
            conditions: { offers: ["execute_code"] },
          },
          { text: answer, conditions: { has_results_for: [callId] } },
        ],
      });
      await chatPage.goto(sessionId);
      await chatPage.inputBar.fill(`Check the service. ${nonce}`);
      await chatPage.inputBar.send();
      for (const view of ["live", "reloaded"]) {
        if (view === "reloaded") await chatPage.reload();
        await chatPage.expectCompleteAnswers(1);
        await chatPage.expectAnswerParagraph(answer);
        await chatPage.expectCustomToolResult(operation, '"status": "ok"');
        await expect(chatPage.aiMessage()).not.toContainText(CODE_MODE_TEXT);
      }
    } finally {
      if (sessionId) await api.deleteChatSession(sessionId);
      if (agentId !== undefined) await adminApi.deleteAgent(agentId);
      await adminApi.deleteCustomTool(toolId);
      await admin.close();
    }
  });
});
