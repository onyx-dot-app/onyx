import { test } from "@tests/e2e/chat/fixtures";
import {
  buildMockStreamWithContextUsage,
  mockChatEndpoint,
} from "@tests/e2e/utils/chatMock";

test.describe("Context-window gauge", () => {
  test("renders usage from the context_usage packet after a turn", async ({
    chatPage,
  }) => {
    await chatPage.goto();

    // 64k of a 128k window -> the gauge should report 50% used.
    await mockChatEndpoint(
      chatPage.page,
      buildMockStreamWithContextUsage("Mock response", 64_000, 128_000)
    );

    await chatPage.inputBar.fill("hello");
    await chatPage.inputBar.send();
    await chatPage.expectHumanMessage("hello");

    await chatPage.expectContextGauge(50);
  });

  test("hides when the stream carries no context usage", async ({
    chatPage,
  }) => {
    await chatPage.goto();
    // A fresh chat with no context_usage packet and no session value -> no gauge.
    await chatPage.expectNoContextGauge();
  });
});
