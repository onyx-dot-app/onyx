import { test, expect } from "@tests/e2e/chat/fixtures";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  addMockLlmConversation,
  mockLlmNonce,
  mockLlmToolCallReply,
  MOCK_LLM_BACKEND_URL,
} from "@tests/e2e/utils/mockLlm";

// Code mode runs behind the scenes; none of it is user-facing copy.
const CODE_MODE_TEXT = /await \w+\(|\bcell\b|Ran code|execute_code|wait_code/i;

test("custom tool output and answer survive a history reload @code-mode", async ({
  browser,
  page,
  chatPage,
  api,
}) => {
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
      `Tool history ${nonce}`,
      [toolId],
      { userIds: [user.id] }
    );
    sessionId = await api.createChatSession("Tool history", agentId);
    const callId = `call-${nonce}`;
    // Matches `CustomTool.name` in the backend.
    const toolName = `custom__${toolId}__${operation}`;
    await addMockLlmConversation({
      name: nonce,
      conditions: { prompt_contains: [nonce] },
      replies: [
        mockLlmToolCallReply([{ id: callId, name: toolName, arguments: {} }]),
        {
          text: "The health check returned ok.",
          conditions: { has_results_for: [callId] },
        },
      ],
    });
    await chatPage.goto(sessionId);
    await chatPage.inputBar.fill(`Check the service. ${nonce}`);
    await chatPage.inputBar.send();
    for (const view of ["live", "reloaded"]) {
      if (view === "reloaded") await chatPage.reload();
      await chatPage.expectCompleteAnswers(1);
      await chatPage.expectAnswerParagraph("The health check returned ok.");
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
