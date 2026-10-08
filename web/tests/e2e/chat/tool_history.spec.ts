import { test, expect } from "@tests/e2e/chat/fixtures";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  addMockLlmConversation,
  mockLlmNonce,
  MOCK_LLM_BACKEND_URL,
} from "@tests/e2e/utils/mockLlm";

test("custom tool output and answer survive a history reload", async ({
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
    await addMockLlmConversation({
      name: nonce,
      conditions: { prompt_contains: [nonce] },
      replies: [
        { tool_calls: [{ id: callId, name: operation, arguments: {} }] },
        {
          text: "The health check returned ok.",
          conditions: { has_results_for: [callId] },
        },
      ],
    });
    await chatPage.goto(sessionId);
    await chatPage.inputBar.fill(`Check the service. ${nonce}`);
    await chatPage.inputBar.send();
    await chatPage.expectCompleteAnswers(1);
    await chatPage.expectAnswerParagraph("The health check returned ok.");
    await chatPage.expectCustomToolResult(operation, '"status": "ok"');
    await page.reload();
    await chatPage.expectCompleteAnswers(1);
    await chatPage.expectAnswerParagraph("The health check returned ok.");
    await chatPage.expectCustomToolResult(operation, '"status": "ok"');
  } finally {
    if (sessionId) await api.deleteChatSession(sessionId);
    if (agentId !== undefined) await adminApi.deleteAgent(agentId);
    await adminApi.deleteCustomTool(toolId);
    await admin.close();
  }
});
