import { test, expect } from "@tests/e2e/chat/fixtures";
import {
  addMockLlmConversation,
  mockLlmNonce,
  releaseMockLlmGate,
} from "@tests/e2e/utils/mockLlm";

const FIRST_PARAGRAPH = "First saved paragraph.";
const HEADING = "Persisted answer";
const LAST_PARAGRAPH =
  "The final paragraph arrives after reconnection and must appear exactly once.";
const ANSWER = `${FIRST_PARAGRAPH}\n\n## ${HEADING}\n\n${LAST_PARAGRAPH}`;

const recoveryTest = test.extend<{ sessionId: string }>({
  sessionId: async ({ api }, use) => {
    const sessionId = await api.createChatSession("Stream recovery");
    try {
      await use(sessionId);
    } finally {
      await api.deleteChatSession(sessionId);
    }
  },
});

for (const recovery of [
  "reload while running",
  "return after completion",
  "reload after network loss",
] as const) {
  recoveryTest(
    `${recovery} preserves the answer and accepts another turn`,
    async ({ page, chatPage, sessionId }) => {
      const nonce = mockLlmNonce();
      const followup = "The next turn also completed.";
      await addMockLlmConversation({
        name: nonce,
        conditions: { prompt_contains: [nonce] },
        replies: [
          { text: ANSWER, pause_after_first_chunk: nonce },
          { text: followup },
        ],
      });
      try {
        await chatPage.goto(sessionId);
        await chatPage.inputBar.fill(`Explain recovery. ${nonce}`);
        await chatPage.inputBar.send();
        await chatPage.expectAnswerParagraph(FIRST_PARAGRAPH);
        await chatPage.expectAnswerAbsent(LAST_PARAGRAPH);

        if (recovery !== "return after completion") {
          if (recovery === "reload after network loss") {
            await page.context().setOffline(true);
            await expect(page.reload()).rejects.toThrow(
              "ERR_INTERNET_DISCONNECTED"
            );
            await page.context().setOffline(false);
          }
          const resumed = page.waitForResponse((response) =>
            response.url().includes(`/chat-session/${sessionId}/resume-stream`)
          );
          await page.reload();
          expect((await resumed).ok()).toBe(true);
          await chatPage.expectAnswerParagraph(FIRST_PARAGRAPH);
          await releaseMockLlmGate(nonce);
        } else {
          await page.goto("about:blank");
          await releaseMockLlmGate(nonce);
          await expect
            .poll(async () => {
              const response = await page.request.get(
                `/api/chat/get-chat-session/${sessionId}`
              );
              expect(response.ok()).toBe(true);
              return response.json();
            })
            .toMatchObject({
              is_processing: false,
              messages: expect.arrayContaining([
                expect.objectContaining({ message: ANSWER }),
              ]),
            });
          await chatPage.goto(sessionId);
        }

        await chatPage.expectCompleteAnswers(1);
        await chatPage.expectAnswerParagraph(FIRST_PARAGRAPH);
        await chatPage.expectAnswerHeading(HEADING);
        await chatPage.expectAnswerParagraph(LAST_PARAGRAPH);
        await page.reload();
        await chatPage.expectCompleteAnswers(1);
        await chatPage.expectAnswerParagraph(FIRST_PARAGRAPH);
        await chatPage.expectAnswerHeading(HEADING);
        await chatPage.expectAnswerParagraph(LAST_PARAGRAPH);

        await chatPage.inputBar.fill("Continue with another turn.");
        await expect(chatPage.inputBar.sendButton).toBeEnabled();
        await chatPage.inputBar.send();
        await chatPage.expectCompleteAnswers(2);
        await chatPage.expectAnswerParagraph(followup);
      } finally {
        await page.context().setOffline(false);
        await releaseMockLlmGate(nonce);
      }
    }
  );
}

recoveryTest(
  "stop settles the interrupted answer before accepting another turn",
  async ({ page, chatPage, sessionId }) => {
    const nonce = mockLlmNonce();
    const followup = "The replacement turn completed without old output.";
    await addMockLlmConversation({
      name: nonce,
      conditions: { prompt_contains: [nonce] },
      replies: [
        { text: ANSWER, pause_after_first_chunk: nonce },
        { text: followup },
      ],
    });
    try {
      await chatPage.goto(sessionId);
      await chatPage.inputBar.fill(`Start an interrupted answer. ${nonce}`);
      await chatPage.inputBar.send();
      await chatPage.expectAnswerParagraph(FIRST_PARAGRAPH);
      const stopped = page.waitForResponse(
        (response) =>
          response.url().includes(`/stop-chat-session/${sessionId}`),
        { timeout: 15000 }
      );
      await chatPage.stop();
      expect((await stopped).ok()).toBe(true);
      await chatPage.expectStopping();
      await releaseMockLlmGate(nonce);
      await chatPage.expectCompleteAnswers(1);
      await chatPage.inputBar.fill("Continue after the interruption.");
      await expect(chatPage.inputBar.sendButton).toBeEnabled();
      await chatPage.inputBar.send();
      await chatPage.expectCompleteAnswers(2);
      await chatPage.expectAnswerParagraph(followup);
      await page.reload();
      await chatPage.expectCompleteAnswers(2);
      await chatPage.expectAnswerParagraph(FIRST_PARAGRAPH);
      await chatPage.expectAnswerParagraph(followup);
      await expect(chatPage.aiMessage(1)).not.toContainText(LAST_PARAGRAPH);
      await expect(chatPage.humanMessages).toHaveCount(2);
    } finally {
      await releaseMockLlmGate(nonce);
    }
  }
);
