import { test, expect } from "@tests/e2e/chat/fixtures";
import {
  addMockLlmConversation,
  getMockLlmConversationRequests,
  mockLlmNonce,
  MOCK_LLM_DEFAULT_RESPONSE,
  releaseMockLlmGate,
} from "@tests/e2e/utils/mockLlm";

test("separate background results reach an idle chat and survive reload @code-mode", async ({
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
    await releaseMockLlmGate(firstReplyGateId);
    await chatPage.expectAnswerParagraph(firstAnswer);
    await expect(chatPage.inputBar.subagentActivity).toBeVisible();
    await releaseMockLlmGate(secondGateId);
    await releaseMockLlmGate(secondReplyGateId);
    await chatPage.expectAnswerParagraph(finalAnswer);
    await expect(chatPage.inputBar.subagentActivity).toBeHidden();
    await expect(chatPage.agentResultsDividers).toHaveCount(2);
    await chatPage.reload();
    await chatPage.expectAnswerParagraph(initialAnswer);
    await chatPage.expectAnswerParagraph(firstAnswer);
    await chatPage.expectAnswerParagraph(finalAnswer);
    await expect(chatPage.agentResultsDividers).toHaveCount(2);
    await expect(chatPage.inputBar.subagentActivity).toBeHidden();
    await expect(chatPage.scrollContainer).not.toContainText(
      "Private child result:"
    );
  } finally {
    await releaseMockLlmGate(gateId);
    await releaseMockLlmGate(secondGateId);
    await releaseMockLlmGate(firstReplyGateId);
    await releaseMockLlmGate(secondReplyGateId);
    if (sessionId) await api.deleteChatSession(sessionId);
  }
});

test("Stop subagents ends background work @code-mode", async ({
  api,
  chatPage,
  page,
}) => {
  const nonce = mockLlmNonce();
  const gateId = mockLlmNonce();
  const question = `Research in the background. ${nonce}`;
  const childTask = `Find the answer. ${gateId}`;
  await addMockLlmConversation({
    name: nonce,
    conditions: { prompt_contains: [question] },
    replies: [
      {
        tool_calls: [
          {
            id: "spawn-research",
            name: "spawn_agent",
            arguments: { name: "research", instruction: childTask },
          },
        ],
      },
      {
        text: "Research is running in the background.",
        conditions: { has_results_for: ["spawn-research"] },
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
    await expect(chatPage.inputBar.subagentActivity).toBeVisible();
    // Stop only after the child reaches the model, so its late result is real.
    await expect
      .poll(async () => (await getMockLlmConversationRequests(gateId)).length)
      .toBeGreaterThan(0);
    const stopped = page.waitForResponse((response) =>
      response.url().endsWith(`/chat-session/${sessionId}/stop-subagents`)
    );
    await chatPage.inputBar.stopSubagentsButton.click();
    expect((await stopped).ok()).toBe(true);
    // The released child can finish its reply; Stop must still drop its result.
    await releaseMockLlmGate(gateId);
    await expect(chatPage.inputBar.subagentActivity).toBeHidden();
    await chatPage.reload();
    await expect(chatPage.inputBar.subagentActivity).toBeHidden();
    await expect(chatPage.agentResultsDividers).toHaveCount(0);
    await expect(chatPage.scrollContainer).not.toContainText(
      "Private child result:"
    );
  } finally {
    await releaseMockLlmGate(gateId);
    if (sessionId) await api.deleteChatSession(sessionId);
  }
});
