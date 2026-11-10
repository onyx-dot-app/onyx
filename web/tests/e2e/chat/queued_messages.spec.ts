import { test, expect } from "@tests/e2e/chat/fixtures";
import {
  addMockLlmConversation,
  mockLlmNonce,
  releaseMockLlmGate,
} from "@tests/e2e/utils/mockLlm";

const pendingTest = test.extend<{
  heldResponse: { sessionId: string; question: string; gateId: string };
}>({
  heldResponse: async ({ api, chatPage }, use) => {
    const sessionId = await api.createChatSession("Pending messages");
    const gateId = mockLlmNonce();
    const question = `Explain queued messages. ${gateId}`;
    await addMockLlmConversation({
      name: gateId,
      conditions: { prompt_contains: [gateId] },
      replies: [
        {
          text: "Working on the first answer.\n\nFirst answer complete.",
          pause_after_first_chunk: gateId,
        },
        { text: "The additional instruction was received." },
      ],
    });
    try {
      await chatPage.goto(sessionId);
      await chatPage.inputBar.fill(question);
      await chatPage.inputBar.send();
      await expect(chatPage.scrollContainer).toContainText("Working on");
      await expect(chatPage.inputBar.container).toBeInViewport({ ratio: 1 });
      await use({ sessionId, question, gateId });
    } finally {
      await releaseMockLlmGate(gateId);
      await api.deleteChatSession(sessionId);
    }
  },
});

pendingTest(
  "queued messages survive reload and execute in order",
  async ({ chatPage, heldResponse }) => {
    await chatPage.inputBar.submitPending("First queued");
    await chatPage.inputBar.submitPending("Second queued");
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(2);
    await expect(chatPage.inputBar.container).toBeInViewport({ ratio: 1 });
    await chatPage.reload();
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(2);
    await expect(chatPage.inputBar.container).toBeInViewport({ ratio: 1 });
    await expect(chatPage.inputBar.queuedMessages.nth(0)).toContainText(
      "First queued"
    );
    await expect(chatPage.inputBar.queuedMessages.nth(1)).toContainText(
      "Second queued"
    );
    await releaseMockLlmGate(heldResponse.gateId);
    await chatPage.expectSavedTurns([
      heldResponse.question,
      "First queued",
      "Second queued",
    ]);
    await chatPage.expectCompleteAnswers(3);
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(0);
    await expect(chatPage.inputBar.container).toBeInViewport({ ratio: 1 });
  }
);

pendingTest(
  "a long queue scrolls without hiding the input",
  async ({ page, chatPage, heldResponse }) => {
    const messageCount = 16;
    for (let index = 0; index < messageCount; index++) {
      await chatPage.inputBar.submitPending(`Pending instruction ${index}`);
      await expect(chatPage.inputBar.queuedMessages).toHaveCount(index + 1);
      await expect(chatPage.inputBar.container).toBeInViewport({ ratio: 1 });
    }

    await chatPage.inputBar.textbox.press("ArrowUp");
    await expect(chatPage.inputBar.queuedMessages.last()).toBeInViewport({
      ratio: 1,
    });
    for (let index = 1; index < messageCount; index++) {
      await chatPage.inputBar.textbox.press("ArrowUp");
    }
    await expect(chatPage.inputBar.queuedMessages.first()).toBeInViewport({
      ratio: 1,
    });
    await expect(chatPage.inputBar.container).toBeInViewport({ ratio: 1 });

    await page.setViewportSize({ width: 390, height: 844 });
    await chatPage.reload();
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(messageCount);
    await expect(chatPage.inputBar.container).toBeInViewport({ ratio: 1 });
    await chatPage.inputBar.textbox.press("ArrowUp");
    await expect(chatPage.inputBar.queuedMessages.last()).toBeInViewport({
      ratio: 1,
    });
    await expect(chatPage.inputBar.container).toBeInViewport({ ratio: 1 });

    for (let remaining = messageCount; remaining > 0; remaining--) {
      await chatPage.inputBar.textbox.press("Delete");
      await expect(chatPage.inputBar.queuedMessages).toHaveCount(remaining - 1);
    }
    await releaseMockLlmGate(heldResponse.gateId);
    await chatPage.expectCompleteAnswers(1);
  }
);

pendingTest(
  "withdraws pending messages before editing and resubmitting them",
  async ({ chatPage, heldResponse }) => {
    await chatPage.inputBar.submitPending("Discard this");
    await chatPage.inputBar.submitPending("Edit this");
    await chatPage.inputBar.discardPending(0);
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(1);
    await chatPage.inputBar.textbox.press("ArrowUp");
    await chatPage.inputBar.textbox.press("Enter");
    await expect(chatPage.inputBar.textbox).toHaveText("Edit this");
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(0);
    await chatPage.reload();
    await chatPage.expectHumanMessage(heldResponse.question);
    await expect(chatPage.inputBar.textbox).toHaveText("Edit this");
    await chatPage.inputBar.submitPending("Edited instruction");
    await releaseMockLlmGate(heldResponse.gateId);
    await chatPage.expectSavedTurns([
      heldResponse.question,
      "Edited instruction",
    ]);
    await chatPage.expectCompleteAnswers(2);
  }
);

pendingTest(
  "Ctrl or Cmd Enter adds an instruction to the active response",
  async ({ page, chatPage, heldResponse }) => {
    const instruction = "Focus on durability";
    await chatPage.inputBar.submitPending(instruction, "send");
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(1);
    await releaseMockLlmGate(heldResponse.gateId);
    await chatPage.expectAnswerParagraph(
      "The additional instruction was received."
    );
    await chatPage.expectCompleteAnswers(1);
    await chatPage.expectSavedTurns([heldResponse.question]);
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(0);
    await expect
      .poll(async () => {
        const response = await page.request.get(
          `/api/chat/get-chat-session/${heldResponse.sessionId}`
        );
        expect(response.ok()).toBe(true);
        return response.json();
      })
      .toMatchObject({
        messages: expect.arrayContaining([
          expect.objectContaining({
            accepted_user_messages: [
              expect.objectContaining({ message: instruction }),
            ],
          }),
        ]),
      });
    await chatPage.reload();
    await expect(chatPage.aiMessage()).toContainText(instruction);
  }
);

pendingTest(
  "Stop leaves the queued message pending",
  async ({ page, chatPage, heldResponse }) => {
    await chatPage.inputBar.submitPending("Keep for later");
    const stopped = page.waitForResponse((response) =>
      response.url().includes(`/stop-chat-session/${heldResponse.sessionId}`)
    );
    await chatPage.stop();
    expect((await stopped).ok()).toBe(true);
    await chatPage.expectStopping();
    await releaseMockLlmGate(heldResponse.gateId);
    await chatPage.expectCompleteAnswers(1);
    await chatPage.reload();
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(1);
    await expect(chatPage.inputBar.queuedMessages).toContainText(
      "Keep for later"
    );
    await chatPage.expectSavedTurns([heldResponse.question]);
  }
);
