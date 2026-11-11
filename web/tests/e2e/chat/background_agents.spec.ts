import { test, expect } from "@tests/e2e/chat/fixtures";
import {
  addMockLlmConversation,
  mockLlmNonce,
  MOCK_LLM_DEFAULT_RESPONSE,
  releaseMockLlmGate,
} from "@tests/e2e/utils/mockLlm";

test("separate background results reach an idle chat and survive reload", async ({
  api,
  chatPage,
  page,
}) => {
  const nonce = mockLlmNonce();
  const gateId = mockLlmNonce();
  const secondGateId = mockLlmNonce();
  const firstReplyGateId = mockLlmNonce();
  const secondReplyGateId = mockLlmNonce();
  const question = `Research in the background. ${nonce}`;
  const childTask = `Find the answer. ${gateId}`;
  const secondChildTask = `Verify the answer. ${secondGateId}`;
  const initialAnswer = "Research is running in the background.";
  const firstAnswer = "The first researcher found forty-two.";
  const finalAnswer = "Verified research answer: forty-two.";
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
          {
            id: "spawn-verification",
            name: "spawn_agent",
            arguments: {
              name: "verification",
              instruction: secondChildTask,
            },
          },
        ],
      },
      {
        text: initialAnswer,
        conditions: {
          has_results_for: ["spawn-research", "spawn-verification"],
        },
      },
      {
        text: firstAnswer,
        pause_after_first_chunk: firstReplyGateId,
        conditions: { prompt_contains: ["Private child result: forty-two."] },
      },
      {
        text: finalAnswer,
        pause_after_first_chunk: secondReplyGateId,
        conditions: { prompt_contains: ["Private child result: verified."] },
      },
    ],
  });
  await addMockLlmConversation({
    name: secondGateId,
    conditions: { prompt_contains: [secondChildTask] },
    replies: [
      {
        text: "Private child result: verified.",
        pause_after_first_chunk: secondGateId,
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
    await chatPage.inputBar.expectCompactSubagentActivity();
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
    await expect(chatPage.scrollContainer).toContainText("The first");
    await chatPage.inputBar.fill("A draft during the automatic reply");
    await expect(chatPage.inputBar.pendingMessageHint).toBeVisible();
    await chatPage.inputBar.expectInlinePendingMessageHint();
    await chatPage.inputBar.clear();
    await releaseMockLlmGate(firstReplyGateId);
    await chatPage.expectAnswerParagraph(firstAnswer);
    await expect(chatPage.inputBar.subagentActivity).toBeVisible();
    await releaseMockLlmGate(secondGateId);
    await expect(chatPage.scrollContainer).toContainText("Verified");
    await chatPage.reload();
    await expect(chatPage.scrollContainer).toContainText("Verified");
    await releaseMockLlmGate(secondReplyGateId);
    await expect(chatPage.scrollContainer).toContainText(finalAnswer);
    await expect(chatPage.inputBar.subagentActivity).toBeHidden();
    await expect(chatPage.regenerateControl(0)).toHaveCount(1);
    await expect(chatPage.regenerateControl(1)).toHaveCount(0);
    await expect(chatPage.humanMessageBubbles).toHaveText([question]);
    await expect(chatPage.scrollContainer).not.toContainText(
      "Private child result:"
    );
    for (let reload = 0; reload < 2; reload++) {
      await chatPage.reload();
      await chatPage.expectAnswerParagraph(initialAnswer);
      await chatPage.expectAnswerParagraph(firstAnswer);
      await chatPage.expectAnswerParagraph(finalAnswer);
      await expect(chatPage.inputBar.subagentActivity).toBeHidden();
      await expect(chatPage.humanMessageBubbles).toHaveText([question]);
      await expect(chatPage.scrollContainer).not.toContainText(
        "Private child result:"
      );
    }
  } finally {
    await releaseMockLlmGate(gateId);
    await releaseMockLlmGate(secondGateId);
    await releaseMockLlmGate(firstReplyGateId);
    await releaseMockLlmGate(secondReplyGateId);
    if (sessionId) await api.deleteChatSession(sessionId);
  }
});
