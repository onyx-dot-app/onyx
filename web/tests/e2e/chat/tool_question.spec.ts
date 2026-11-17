import { test, expect } from "@tests/e2e/chat/fixtures";
import {
  addMockLlmConversation,
  getMockLlmConversationRequests,
  mockLlmNonce,
  type MockLlmReply,
} from "@tests/e2e/utils/mockLlm";
import { ToolQuestionCard } from "@tests/e2e/pages/ToolQuestionCard";

// The question tool's name for the mock model.
const QUESTION_TOOL = "request_user_input";

interface AskedQuestion {
  id: string;
  header: string;
  question: string;
  options: string[];
}

function askReply(callId: string, questions: AskedQuestion[]): MockLlmReply {
  return {
    tool_calls: [
      {
        id: callId,
        name: QUESTION_TOOL,
        arguments: {
          questions: questions.map((question) => ({
            id: question.id,
            header: question.header,
            question: question.question,
            options: question.options.map((label) => ({
              label,
              description: `Choose ${label}.`,
            })),
          })),
        },
      },
    ],
    // The tool runs natively also in code mode.
    conditions: { offers: [QUESTION_TOOL] },
  };
}

/**
 * The agent asks the user questions and waits. The user answers on the
 * card, one question per page, or types the answer in the chat, which shows as the
 * user's message. The reply continues after the answer, and a reload shows
 * the same records.
 */
test("the user answers the agent's questions on the card and in the chat", async ({
  chatPage,
  api,
  page,
}) => {
  const nonce = mockLlmNonce();
  const firstCall = `call-scope-${nonce}`;
  const secondCall = `call-format-${nonce}`;
  await addMockLlmConversation({
    name: nonce,
    conditions: { prompt_contains: [nonce] },
    replies: [
      askReply(firstCall, [
        {
          id: "scope",
          header: "Scope",
          question: "Which files should I change?",
          options: ["All files (Recommended)", "Docs only"],
        },
        {
          id: "audience",
          header: "Audience",
          question: "Who reads the docs?",
          options: ["Admins (Recommended)", "End users"],
        },
      ]),
      {
        text: "I will update the docs and the README.",
        conditions: { has_results_for: [firstCall] },
      },
      askReply(secondCall, [
        {
          id: "format",
          header: "Format",
          question: "How should the release notes look?",
          options: ["Bullets (Recommended)", "Prose"],
        },
      ]),
      {
        text: "The release notes are drafted.",
        conditions: { has_results_for: [secondCall] },
      },
    ],
  });
  const questions = new ToolQuestionCard(page);
  const sessionId = await api.createChatSession("Tool questions");
  try {
    await chatPage.goto(sessionId);

    // Two questions on two pages: an Other answer, then an option.
    await chatPage.inputBar.fill(`Plan the docs change. ${nonce}`);
    await chatPage.inputBar.send();
    await questions.expectPending("Which files should I change?");
    await questions.expectPage(1, 2);
    await questions.expectOptions(["All files (Recommended)", "Docs only"]);
    await questions.typeOther("Scope", "Docs and the README");
    await questions.next();
    await questions.expectPending("Who reads the docs?");
    await questions.expectPage(2, 2);
    await questions.choose("End users");
    // The first page keeps its choice.
    await questions.back();
    await questions.expectOther("Scope", "Docs and the README");
    await questions.next();
    await questions.submit();
    await chatPage.expectAnswerParagraph(
      "I will update the docs and the README."
    );
    await questions.expectRecord("Answered", "Scope: Docs and the README");
    await questions.expectRecord("Answered", "Audience: End users");

    // A message typed in the chat answers the second question. Text sent
    // before the reply settles would join that turn.
    await chatPage.expectLatestReplyComplete();
    await chatPage.inputBar.fill(`Now the release notes. ${nonce}`);
    await chatPage.inputBar.send();
    await questions.expectPending("How should the release notes look?");
    await chatPage.inputBar.fill("Use a short table");
    await chatPage.inputBar.send();
    await chatPage.expectHumanMessageBubble("Use a short table", 30_000);
    await chatPage.expectAnswerParagraph("The release notes are drafted.");
    await chatPage.inputBar.expectIdle();
    await chatPage.expectSavedTurns([
      `Plan the docs change. ${nonce}`,
      `Now the release notes. ${nonce}`,
    ]);

    // The agent read the card's answer as JSON and the message as typed.
    const requests = await getMockLlmConversationRequests(nonce);
    const results = new Map(
      requests
        .flatMap((request) => request.messages)
        .filter((message) => message.role === "tool")
        .map((message) => [message.tool_call_id, message.content])
    );
    expect(JSON.parse(results.get(firstCall) ?? "null")).toEqual({
      answers: {
        scope: { answers: ["user_note: Docs and the README"] },
        audience: { answers: ["End users"] },
      },
    });
    expect(results.get(secondCall)).toBe("Use a short table");

    await chatPage.reload();
    await questions.expectRecord("Answered", "Scope: Docs and the README");
    await questions.expectRecord(
      "Answered in the chat",
      "How should the release notes look?"
    );
    await chatPage.expectHumanMessageBubble("Use a short table");
    await chatPage.expectAnswerParagraph("The release notes are drafted.");
  } finally {
    await api.deleteChatSession(sessionId);
  }
});
