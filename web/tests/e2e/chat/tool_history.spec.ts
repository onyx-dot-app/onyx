import { test, expect } from "@tests/e2e/chat/fixtures";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  addMockLlmConversation,
  mockLlmNonce,
  mockLlmToolCallReply,
  MOCK_LLM_BACKEND_URL,
} from "@tests/e2e/utils/mockLlm";

// Code mode runs behind the scenes; none of it is user-facing copy.
const CODE_MODE_TEXT =
  /await [\w.]+\(|\bcell\b|Ran code|execute_code|wait_code/i;

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
  const created = await adminApi.createIntegration({
    for_organization: true,
    name: `Health ${nonce}`,
    description: "Read service health",
    auth_mode: "none",
    auth_method: null,
    credential_fields: null,
    header_template: null,
    oauth_client: null,
    config: {
      shape: "openapi",
      openapi_spec: {
        openapi: "3.0.0",
        info: {
          title: `Health ${nonce}`,
          description: "Read service health",
          version: "1.0.0",
        },
        servers: [{ url: MOCK_LLM_BACKEND_URL }],
        paths: {
          "/health": {
            get: {
              operationId: operation,
              summary: "Read service health",
              responses: { "200": { description: "OK" } },
            },
          },
        },
      },
    },
  });
  let agentId: number | undefined;
  let sessionId: string | undefined;
  try {
    const me = await page.request.get("/api/me");
    expect(me.ok()).toBe(true);
    const user: { id: string } = await me.json();
    agentId = await adminApi.createAgentWithIntegrations(
      `Tool history ${nonce}`,
      [created.id],
      { userIds: [user.id] }
    );
    sessionId = await api.createChatSession("Tool history", agentId);
    const callId = `call-${nonce}`;
    // Matches `CustomTool.name` in the backend.
    const toolName = `custom__${created.id}__${operation}`;
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
    await adminApi.deleteIntegration(created.id);
    await admin.close();
  }
});
