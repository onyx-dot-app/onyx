import { test, expect } from "@tests/e2e/chat/fixtures";
import {
  addMockLlmConversation,
  mockLlmNonce,
  MOCK_LLM_DEFAULT_RESPONSE,
  releaseMockLlmGate,
} from "@tests/e2e/utils/mockLlm";

test("background results reach an idle chat without another user message", async ({
  api,
  chatPage,
  page,
}) => {
  const nonce = mockLlmNonce();
  const gateId = mockLlmNonce();
  const question = `Research in the background. ${nonce}`;
  const childTask = `Find the answer. ${gateId}`;
  const initialAnswer = "Research is running in the background.";
  const finalAnswer = "The research answer is forty-two.";
  await addMockLlmConversation({
    name: nonce,
    conditions: { prompt_contains: [question] },
    replies: [
      {
        tool_calls: [
          {
            id: "spawn-research",
            name: "spawn_agent",
            arguments: {
              name: "research",
              instruction: childTask,
            },
          },
        ],
      },
      {
        text: initialAnswer,
        conditions: { has_results_for: ["spawn-research"] },
      },
      {
        text: finalAnswer,
        conditions: { prompt_contains: ["Private child result: forty-two."] },
      },
    ],
  });
  await addMockLlmConversation({
    name: gateId,
    conditions: { prompt_contains: [childTask] },
    replies: [
      {
        text: "Private child result: forty-two.",
        pause_after_first_chunk: gateId,
      },
    ],
  });
  let sessionId: string | null = null;
  try {
    await chatPage.goto();
    await chatPage.inputBar.fill(question);
    const created = page.waitForResponse((response) =>
      response.url().endsWith("/chat/create-chat-session")
    );
    await chatPage.inputBar.send();
    const session: { chat_session_id: string } = await (await created).json();
    sessionId = session.chat_session_id;
    await expect(chatPage.scrollContainer).toContainText(initialAnswer);
    await expect(chatPage.inputBar.subagentActivity).toHaveText(
      "Subagents working"
    );
    await expect(chatPage.inputBar.sendButton).toBeDisabled();
    await chatPage.inputBar.fill("A draft while research continues");
    await expect(chatPage.inputBar.sendButton).toBeEnabled();
    await chatPage.reload();
    await expect(chatPage.inputBar.subagentActivity).toBeVisible();
    await chatPage.editHumanMessage("Use a separate branch without research.");
    await chatPage.submitHumanMessageEdit();
    await expect(chatPage.scrollContainer).toContainText(
      MOCK_LLM_DEFAULT_RESPONSE
    );
    await expect(chatPage.inputBar.subagentActivity).toBeHidden();
    await chatPage.selectPreviousHumanMessage();
    await expect(chatPage.scrollContainer).toContainText(initialAnswer);
    await expect(chatPage.inputBar.subagentActivity).toBeVisible();
    await releaseMockLlmGate(gateId);
    await expect(chatPage.scrollContainer).toContainText(finalAnswer);
    await expect(chatPage.inputBar.subagentActivity).toBeHidden();
    await expect(chatPage.regenerateControl(0)).toHaveCount(1);
    await expect(chatPage.regenerateControl(1)).toHaveCount(0);
    await expect(chatPage.humanMessageBubbles).toHaveText([question]);
    await expect(chatPage.scrollContainer).not.toContainText(
      "Private child result:"
    );
    await chatPage.reload();
    await expect(chatPage.scrollContainer).toContainText(initialAnswer);
    await expect(chatPage.scrollContainer).toContainText(finalAnswer);
    await expect(chatPage.humanMessageBubbles).toHaveText([question]);
  } finally {
    await releaseMockLlmGate(gateId);
    if (sessionId) await api.deleteChatSession(sessionId);
  }
});
