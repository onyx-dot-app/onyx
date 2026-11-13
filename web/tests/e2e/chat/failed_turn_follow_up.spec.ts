import { test, expect } from "@tests/e2e/chat/fixtures";
import {
  addMockLlmConversation,
  getMockLlmConversationRequests,
  mockLlmNonce,
} from "@tests/e2e/utils/mockLlm";

const PARTIAL_ANSWER = "Partial answer before the provider failed.";
const RECOVERED_ANSWER = "Recovered answer after the failure.";
const FOLLOW_UP = "Try again from the partial answer.";

test("a message after a failed answer continues the conversation", async ({
  chatPage,
}) => {
  const nonce = mockLlmNonce();
  const question = `Summarize the plan. ${nonce}`;
  await addMockLlmConversation({
    name: nonce,
    // The second turn matches only if its history keeps the first question.
    conditions: { prompt_contains: [nonce] },
    replies: [
      { text: PARTIAL_ANSWER, error_after_text: "Provider failed" },
      { text: RECOVERED_ANSWER, conditions: { prompt_contains: [FOLLOW_UP] } },
    ],
  });

  await chatPage.goto();
  await chatPage.inputBar.fill(question);
  await chatPage.inputBar.send();
  await chatPage.expectFailedAnswer(1, PARTIAL_ANSWER, true);
  await chatPage.inputBar.expectIdle();

  await chatPage.inputBar.fill(FOLLOW_UP);
  await chatPage.inputBar.send();
  await chatPage.expectAnswerParagraph(RECOVERED_ANSWER);
  await chatPage.expectLatestReplyComplete();
  // Rows: question, failed answer, follow-up, new answer.
  await chatPage.expectFailedAnswer(1, PARTIAL_ANSWER, false);
  await chatPage.expectRowText(2, FOLLOW_UP);
  await chatPage.expectRowText(3, RECOVERED_ANSWER);

  const requests = await getMockLlmConversationRequests(nonce);
  expect(requests).toHaveLength(2);
  const history = requests[1]!.messages.map((message) => [
    message.role,
    message.content,
  ]);
  const questionIndex = history.findIndex(
    ([role, content]) => role === "user" && content!.includes(question)
  );
  const partialIndex = history.findIndex(
    ([role, content]) => role === "assistant" && content === PARTIAL_ANSWER
  );
  const followUpIndex = history.findIndex(
    ([role, content]) => role === "user" && content!.includes(FOLLOW_UP)
  );
  expect(questionIndex).toBeGreaterThanOrEqual(0);
  expect(partialIndex).toBeGreaterThan(questionIndex);
  expect(followUpIndex).toBeGreaterThan(partialIndex);
});
