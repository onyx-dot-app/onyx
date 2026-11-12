import { test, expect } from "@tests/e2e/chat/fixtures";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { UserChatPreferencesPage } from "@tests/e2e/pages/UserChatPreferencesPage";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";
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
  // A user per test, so a changed send preference reaches no other test.
  chatPage: async ({ page }, use) => {
    await page.context().clearCookies();
    await loginAsRandomUser(page);
    await use(new ChatPage(page));
  },
  heldResponse: async ({ api, chatPage, page, providerHeartbeat }, use) => {
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
  "queued messages survive reload and then run",
  async ({ chatPage, heldResponse }) => {
    await chatPage.inputBar.fill("First queued");
    await expect(chatPage.inputBar.pendingMessageHint).toHaveText(
      /Send.*Queue/
    );
    await expect(chatPage.inputBar.sendButton).toHaveText("");
    await chatPage.inputBar.queue();
    await expect(chatPage.inputBar.textbox).toHaveText("");
    await expect(chatPage.inputBar.pendingMessageHint).toHaveCount(0);
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(1);
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

    await chatPage.inputBar.selectPreviousPending();
    await expect(chatPage.inputBar.queuedMessages.last()).toBeInViewport({
      ratio: 1,
    });
    for (let index = 1; index < messageCount; index++) {
      await chatPage.inputBar.selectPreviousPending();
    }
    await expect(chatPage.inputBar.queuedMessages.first()).toBeInViewport({
      ratio: 1,
    });
    await expect(chatPage.inputBar.container).toBeInViewport({ ratio: 1 });

    await page.setViewportSize({ width: 390, height: 844 });
    await chatPage.reload();
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(messageCount);
    await expect(chatPage.inputBar.container).toBeInViewport({ ratio: 1 });
    await chatPage.inputBar.selectPreviousPending();
    await expect(chatPage.inputBar.queuedMessages.last()).toBeInViewport({
      ratio: 1,
    });
    await expect(chatPage.inputBar.container).toBeInViewport({ ratio: 1 });

    for (let remaining = messageCount; remaining > 0; remaining--) {
      await chatPage.inputBar.discardSelectedPending();
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
    expect((await submission).ok()).toBe(true);
    await expect(chatPage.inputBar.queuedMessages).toHaveCount(1);
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
    const copied = await chatPage.copyAnswerHtml();
    expect(copied).toContain("First answer complete.");
    expect(copied).toContain("The additional instruction was received.");
    expect(copied).not.toContain(instruction);
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

pendingTest.describe("Interrupt and send", () => {
  pendingTest.use({ providerHeartbeat: true });

  pendingTest(
    "a queued message can interrupt the response using Enter",
    async ({ page, chatPage, heldResponse }) => {
      await chatPage.inputBar.submitPending("Keep this follow-up queued");
      await chatPage.inputBar.submitPending("Change direction now");
      await expect(chatPage.inputBar.queuedMessages).toHaveCount(2);
      const promoted = page.waitForResponse((response) =>
        new URL(response.url()).pathname.endsWith("/interrupt")
      );
      await chatPage.inputBar.selectPreviousPending();
      await chatPage.inputBar.send();
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

  pendingTest(
    "the interrupt preference applies to the send arrow and survives reload",
    async ({ page, chatPage, heldResponse }) => {
      const preferences = new UserChatPreferencesPage(page);
      await preferences.goto();
      await expect(preferences.sendBehavior).toHaveValue(
        "After the current step"
      );
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
      await chatPage.inputBar.clickSend();
      await chatPage.expectSavedTurns([
        heldResponse.question,
        "Respond to this instead",
        "Still queue this follow-up",
      ]);
      await chatPage.expectCompleteAnswers(3);
      await chatPage.expectAnswerAbsent("First answer complete.");
    }
  );
});
