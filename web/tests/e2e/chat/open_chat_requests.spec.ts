import type { Request } from "@playwright/test";
import { test, expect } from "@tests/e2e/chat/fixtures";
import { MOCK_LLM_DEFAULT_MODEL } from "@tests/e2e/utils/mockLlm";

test("opening a chat loads its history once and writes nothing", async ({
  chatPage,
  api,
}) => {
  const sessionId = await api.createChatSession("Open chat requests");
  const requests: Request[] = [];
  chatPage.page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/"))
      requests.push(request);
  });

  try {
    // The open is settled once the chat's history and the session list are
    // loaded and its model resolved: every request the open makes follows
    // from these.
    const historyLoaded = chatPage.page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          `/api/chat/get-chat-session/${sessionId}` && response.ok()
    );
    const sessionListLoaded = chatPage.page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          "/api/chat/get-user-chat-sessions" && response.ok()
    );
    await chatPage.goto(sessionId);
    await Promise.all([historyLoaded, sessionListLoaded]);
    await chatPage.expectModelPill(MOCK_LLM_DEFAULT_MODEL.displayName);

    const matching = (pattern: RegExp, method?: string): string[] =>
      requests
        .filter(
          (request) =>
            pattern.test(new URL(request.url()).pathname) &&
            (method === undefined || request.method() === method)
        )
        .map((request) => `${request.method()} ${request.url()}`);
    // React StrictMode in development mounts twice and aborts the first
    // load, so only loads that completed count.
    expect
      .soft(
        requests
          .filter(
            (request) =>
              request.method() === "GET" &&
              new URL(request.url()).pathname ===
                `/api/chat/get-chat-session/${sessionId}` &&
              request.failure() === null
          )
          .map((request) => request.url())
      )
      .toHaveLength(1);
    expect.soft(matching(/^\/api\/query\/valid-tags$/)).toEqual([]);
    expect.soft(matching(/^\/api\/manage\/document-set$/)).toEqual([]);
    expect
      .soft(
        matching(
          /^\/api\/chat\/update-chat-session-(temperature|reasoning)$/,
          "PUT"
        )
      )
      .toEqual([]);
    expect
      .soft(matching(/^\/api\/user\/projects\/session\/[^/]+\/files$/))
      .toEqual([]);
  } finally {
    await api.deleteChatSession(sessionId);
  }
});
