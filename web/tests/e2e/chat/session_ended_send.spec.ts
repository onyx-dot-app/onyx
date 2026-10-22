import type { Page } from "@playwright/test";
import { test } from "@tests/e2e/chat/fixtures";
import { SessionEndedModal } from "@tests/e2e/pages/SessionEndedModal";
import {
  buildMockStream,
  mockChatEndpoint,
  resetTurnCounter,
} from "@tests/e2e/utils/chatMock";

const SESSION_TERMINATED_BODY = JSON.stringify({
  error_code: "SESSION_TERMINATED",
  detail: "Session terminated",
});

// Mocks a session revoked elsewhere (e.g. a password change in another tab).
async function revokeSession(page: Page, endpoint: string): Promise<void> {
  for (const url of [endpoint, "**/api/me"]) {
    await page.route(url, async (route) => {
      await route.fulfill({
        status: 403,
        contentType: "application/json",
        body: SESSION_TERMINATED_BODY,
      });
    });
  }
}

test.describe("Chat send after the session ends", () => {
  test.beforeEach(async ({ chatPage }) => {
    resetTurnCounter();
    await chatPage.goto();
  });

  test("a new chat shows the modal and keeps the message", async ({
    chatPage,
  }) => {
    await revokeSession(chatPage.page, "**/api/chat/create-chat-session");

    await chatPage.inputBar.fill("message after revoke");
    await chatPage.inputBar.send();

    await new SessionEndedModal(chatPage.page).expectVisible();
    await chatPage.inputBar.expectText("message after revoke");
  });

  test("an existing chat shows the modal", async ({ chatPage }) => {
    await mockChatEndpoint(chatPage.page, buildMockStream("Mock response"));
    await chatPage.inputBar.fill("first message");
    await chatPage.inputBar.send();
    await chatPage.expectHumanMessage("first message");

    await revokeSession(chatPage.page, "**/api/chat/send-chat-message");

    await chatPage.inputBar.fill("second message");
    await chatPage.inputBar.send();

    await new SessionEndedModal(chatPage.page).expectVisible();
  });
});
