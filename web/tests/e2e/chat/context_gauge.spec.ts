import { test } from "@tests/e2e/chat/fixtures";
import {
  buildMockStream,
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

  test("stays hidden when a turn streams no context_usage packet", async ({
    chatPage,
  }) => {
    await chatPage.goto();
    // Models/paths that don't report usage emit no context_usage packet -> no gauge.
    await mockChatEndpoint(chatPage.page, buildMockStream("Mock response"));

    await chatPage.inputBar.fill("hello");
    await chatPage.inputBar.send();
    await chatPage.expectHumanMessage("hello");

    await chatPage.expectNoContextGauge();
  });
});
