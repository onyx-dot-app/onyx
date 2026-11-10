import { test, expect } from "@tests/e2e/chat/fixtures";
import { UserChatPreferencesPage } from "@tests/e2e/pages/UserChatPreferencesPage";
import {
  addMockLlmConversation,
  mockLlmNonce,
  releaseMockLlmGate,
} from "@tests/e2e/utils/mockLlm";

const pendingTest = test.extend<{
  providerHeartbeat: boolean;
  heldResponse: { sessionId: string; question: string; gateId: string };
}>({
  providerHeartbeat: [false, { option: true }],
  heldResponse: async ({ api, chatPage, page, providerHeartbeat }, use) => {
    const preference = await page.request.patch(
      "/api/interrupt-on-send?interrupt_on_send=false"
    );
    expect(preference.ok()).toBe(true);
    let sessionId: string | null = null;
    const gateId = mockLlmNonce();
    const question = `Explain queued messages. ${gateId}`;
    await addMockLlmConversation({
      name: gateId,
      conditions: { prompt_contains: [gateId] },
      replies: [
        {
          text: "Working on the first answer.\n\nFirst answer complete.",
          pause_after_first_chunk: gateId,
          heartbeat_while_paused: providerHeartbeat,
        },
        { text: "The additional instruction was received." },
      ],
    });
    try {
      await chatPage.goto();
      await chatPage.inputBar.fill(question);
      const created = page.waitForResponse((response) =>
        response.url().endsWith("/chat/create-chat-session")
      );
      await chatPage.inputBar.send();
      const createdResponse = await created;
      expect(createdResponse.ok()).toBe(true);
      const session: { chat_session_id: string } = await createdResponse.json();
      sessionId = session.chat_session_id;
      await expect(chatPage.scrollContainer).toContainText("Working on");
      await expect(chatPage.inputBar.container).toBeInViewport({ ratio: 1 });
      await expect(chatPage.inputBar.pendingMessageHint).toHaveCount(0);
      await use({ sessionId, question, gateId });
    } finally {
      await releaseMockLlmGate(gateId);
      if (sessionId) await api.deleteChatSession(sessionId);
    }
  },
});

pendingTest(
  "queued messages survive reload and execute in order",
  async ({ chatPage, heldResponse }) => {
    await chatPage.inputBar.fill("First queued");
    await expect(chatPage.inputBar.pendingMessageHint).toBeVisible();
    await expect(chatPage.inputBar.sendButton).toHaveText("");
    await expect(chatPage.inputBar.composerSendNowButton).toHaveCount(0);
    await chatPage.inputBar.textbox.press("ControlOrMeta+Enter");
    await expect(chatPage.inputBar.textbox).toHaveText("");
    await expect(chatPage.inputBar.pendingMessageHint).toHaveCount(0);
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
  "previews the next queued turn while saved history is loading",
  async ({ page, chatPage, heldResponse }) => {
    await chatPage.inputBar.submitPending("Next queued question");
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(1);
    let releaseHistory!: () => void;
    const historyReady = new Promise<void>((resolve) => {
      releaseHistory = resolve;
    });
    const historyRoute = `**/api/chat/get-chat-session/${heldResponse.sessionId}*`;
    await page.route(historyRoute, async (route) => {
      await historyReady;
      await route.continue();
    });
    try {
      await releaseMockLlmGate(heldResponse.gateId);
      await expect(chatPage.queuedMessageHandoff).toContainText(
        "Next queued question"
      );
      await expect(chatPage.inputBar.queuedMessages).toHaveCount(0);
      await expect(chatPage.humanMessageBubbles).toHaveText([
        heldResponse.question,
        "Next queued question",
      ]);
      await expect(chatPage.inputBar.container).toBeInViewport({ ratio: 1 });
      releaseHistory();
      await chatPage.expectSavedTurns([
        heldResponse.question,
        "Next queued question",
      ]);
      await chatPage.expectCompleteAnswers(2);
      await expect(chatPage.queuedMessageHandoff).toHaveCount(0);
      await expect(chatPage.humanMessageBubbles).toHaveText([
        heldResponse.question,
        "Next queued question",
      ]);
    } finally {
      releaseHistory();
      await page.unroute(historyRoute);
    }
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
    await chatPage.inputBar.editPending(0);
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
  "Enter adds an instruction after the current step",
  async ({ page, chatPage, heldResponse }) => {
    const instruction = "Focus on durability";
    const submission = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response
          .url()
          .endsWith(`/chat-session/${heldResponse.sessionId}/pending-messages`)
    );
    await chatPage.inputBar.submitPending(instruction, "send");
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(1);
    // The optimistic tile appears before the server accepts the instruction.
    expect((await submission).ok()).toBe(true);
    await releaseMockLlmGate(heldResponse.gateId);
    await chatPage.expectAnswerParagraph(
      "The additional instruction was received."
    );
    await chatPage.expectCompleteAnswers(1);
    await chatPage.expectSavedTurns([heldResponse.question]);
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(0);
    await expect(chatPage.humanMessageBubbles).toHaveText([
      heldResponse.question,
      instruction,
    ]);
    await expect(chatPage.scrollContainer).toContainText(
      /First answer complete\.[\s\S]*Focus on durability[\s\S]*The additional instruction was received\./
    );
    await chatPage.reload();
    await expect(chatPage.humanMessageBubbles).toHaveText([
      heldResponse.question,
      instruction,
    ]);
    await expect(chatPage.scrollContainer).toContainText(
      /First answer complete\.[\s\S]*Focus on durability[\s\S]*The additional instruction was received\./
    );
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

pendingTest.describe("Interrupt and send", () => {
  pendingTest.use({ providerHeartbeat: true });

  for (const action of ["button", "Enter"] as const) {
    pendingTest(
      `a queued message can interrupt the response using ${action}`,
      async ({ page, chatPage, heldResponse }) => {
        await chatPage.inputBar.submitPending("Keep this follow-up queued");
        await chatPage.inputBar.submitPending("Change direction now");
        await expect(chatPage.inputBar.queuedMessages).toHaveCount(2);
        const promoted = page.waitForResponse((response) =>
          new URL(response.url()).pathname.endsWith("/interrupt")
        );
        if (action === "button") {
          await chatPage.inputBar.sendPendingNow(1);
        } else {
          await chatPage.inputBar.textbox.press("ArrowUp");
          await chatPage.inputBar.textbox.press("Enter");
        }
        expect((await promoted).ok()).toBe(true);
        await chatPage.expectSavedTurns([
          heldResponse.question,
          "Change direction now",
          "Keep this follow-up queued",
        ]);
        await chatPage.expectCompleteAnswers(3);
        await chatPage.expectAnswerAbsent("First answer complete.");
        await expect(chatPage.inputBar.queuedMessages).toHaveCount(0);
        await chatPage.reload();
        await expect(chatPage.humanMessageBubbles).toHaveText([
          heldResponse.question,
          "Change direction now",
          "Keep this follow-up queued",
        ]);
        await chatPage.expectAnswerAbsent("First answer complete.");
      }
    );
  }

  for (const action of ["Enter", "send arrow"] as const) {
    pendingTest(
      `the interrupt preference applies to ${action} and survives reload`,
      async ({ page, chatPage, heldResponse }) => {
        const preferences = new UserChatPreferencesPage(page);
        await preferences.goto();
        await expect(preferences.sendBehavior).toHaveValue(
          "After the current step"
        );
        try {
          await preferences.setSendBehavior("Interrupt current work");
          await page.reload();
          await expect(preferences.sendBehavior).toHaveValue(
            "Interrupt current work"
          );
          await chatPage.goto(heldResponse.sessionId);
          await expect(chatPage.scrollContainer).toContainText("Working on");
          await chatPage.inputBar.submitPending("Still queue this follow-up");
          await expect(chatPage.inputBar.queuedMessages).toHaveCount(1);
          await chatPage.expectSavedTurns([heldResponse.question]);
          await chatPage.expectAnswerAbsent("First answer complete.");
          await chatPage.inputBar.fill("Respond to this instead");
          if (action === "Enter") {
            await chatPage.inputBar.send();
          } else {
            await chatPage.inputBar.clickSend();
          }
          await chatPage.expectSavedTurns([
            heldResponse.question,
            "Respond to this instead",
            "Still queue this follow-up",
          ]);
          await chatPage.expectCompleteAnswers(3);
          await chatPage.expectAnswerAbsent("First answer complete.");
        } finally {
          const reset = await page.request.patch(
            "/api/interrupt-on-send?interrupt_on_send=false"
          );
          expect(reset.ok()).toBe(true);
        }
      }
    );
  }
});
