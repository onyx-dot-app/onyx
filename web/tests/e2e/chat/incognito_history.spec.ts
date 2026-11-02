import { test, expect } from "@tests/e2e/chat/fixtures";
import {
  addMockLlmConversation,
  mockLlmNonce,
  getMockLlmConversationRequests,
  MOCK_LLM_DEFAULT_MODEL,
} from "@tests/e2e/utils/mockLlm";

test("incognito preserves accepted history through Stop and retry, then removes it on exit @exclusive", async ({
  browser,
  page,
  chatPage,
  api,
}) => {
  const admin = await browser.newContext({
    storageState: "admin_auth.json",
    baseURL: process.env.BASE_URL || "http://localhost:3000",
  });
  const settingsResponse = await admin.request.get("/api/admin/security");
  expect(settingsResponse.ok()).toBe(true);
  const settings: {
    incognito_availability: string;
    incognito_record_mode: string;
  } = await settingsResponse.json();
  const nonce = mockLlmNonce();
  const overrideGate = Promise.withResolvers<void>();
  const overrideRoute = "**/api/chat/update-chat-session-temperature";
  let sessionId: string | null = null;
  try {
    const enabled = await admin.request.put("/api/admin/security", {
      data: {
        incognito_availability: "everyone",
        incognito_record_mode: "usage_only",
      },
    });
    expect(enabled.ok()).toBe(true);
    await addMockLlmConversation({
      name: nonce,
      conditions: { prompt_contains: [nonce] },
      replies: [
        {
          text: "Private first paragraph.\n\nThe private answer remains available for the next turn.",
        },
        {
          text: "Private context is still available.",
        },
      ],
    });
    await chatPage.goto();
    await chatPage.startIncognito();
    await chatPage.inputBar.fill(`Keep this conversation private. ${nonce}`);
    await chatPage.inputBar.send();
    await chatPage.expectAnswerParagraph("Private first paragraph.");
    sessionId = new URL(page.url()).searchParams.get("chatId");
    expect(sessionId).not.toBeNull();
    await chatPage.expectIncognito();
    await chatPage.expectCompleteAnswers(1);
    await page.route(overrideRoute, async (route) => {
      await overrideGate.promise;
      await route.continue();
    });
    const overrideStarted = page.waitForRequest(
      (request) =>
        request.method() === "PUT" &&
        request.url().endsWith("/update-chat-session-temperature")
    );
    await chatPage.maximizeModelTemperature(MOCK_LLM_DEFAULT_MODEL.displayName);

    const followup = "Use the private context to continue.";
    await chatPage.inputBar.fill(followup);
    await chatPage.inputBar.send();
    await overrideStarted;
    await expect(chatPage.humanMessages).toHaveCount(2);
    await chatPage.stop();
    await chatPage.inputBar.expectText(followup);
    await expect(chatPage.humanMessages).toHaveCount(1);
    await expect(chatPage.aiMessages).toHaveCount(1);
    expect(await getMockLlmConversationRequests(nonce)).toHaveLength(1);

    overrideGate.resolve();
    await expect(chatPage.inputBar.sendButton).toBeEnabled();
    await chatPage.inputBar.send();
    await chatPage.expectCompleteAnswers(2);
    await chatPage.expectAnswerParagraph("Private context is still available.");
    await expect(chatPage.humanMessages).toHaveCount(2);
    const requests = await getMockLlmConversationRequests(nonce);
    expect(requests).toHaveLength(2);
    expect(requests[1]?.messages).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          role: "assistant",
          content: expect.stringContaining("Private first paragraph."),
        }),
      ])
    );
    await chatPage.expectIncognito();
    if (!sessionId) throw new Error("Incognito session has no URL ID");
    await chatPage.expectNoSessionLink(sessionId);
    await chatPage.exitIncognito();
    await chatPage.reload();
    await chatPage.expectNoHumanMessages();
    await chatPage.expectNoSessionLink(sessionId);
    await expect(chatPage.aiMessages).toHaveCount(0);
  } finally {
    overrideGate.resolve();
    await page.unrouteAll({ behavior: "wait" });
    if (sessionId) await api.deleteChatSession(sessionId);
    const restored = await admin.request.put("/api/admin/security", {
      data: {
        incognito_availability: settings.incognito_availability,
        incognito_record_mode: settings.incognito_record_mode,
      },
    });
    expect(restored.ok()).toBe(true);
    await admin.close();
  }
});
