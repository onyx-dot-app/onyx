import { test, expect } from "@tests/e2e/chat/fixtures";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import { buildMockStream } from "@tests/e2e/utils/chatMock";

test.describe("Background Chat Processing", () => {
  test("renders answer from a single-burst NDJSON response (simulating background-processed output)", async ({
    page,
    chatPage,
  }) => {
    await chatPage.goto();

    const mockResponse =
      "This is a response delivered as a single burst of NDJSON lines, simulating the service worker background-processed output.";

    await page.route("**/api/chat/send-chat-message", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/plain",
        body: buildMockStream(mockResponse),
      });
    });

    await sendMessage(page, "test message");

    const aiMessage = page.getByTestId("onyx-ai-message").first();
    await expect(aiMessage).toContainText(mockResponse, {
      timeout: 15000,
    });
  });

  test("renders long content delivered as single burst correctly", async ({
    page,
    chatPage,
  }) => {
    await chatPage.goto();

    const longAnswer =
      "This is a much longer response that would normally stream incrementally. ".repeat(
        20
      ) +
      "When delivered by the service worker, all content arrives at once and the frontend handles it identically. " +
      "The chat controller processes all packets from the FIFO without delay. " +
      "Citations, documents, and tool calls all arrive in a single burst.";

    await page.route("**/api/chat/send-chat-message", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/plain",
        body: buildMockStream(longAnswer),
      });
    });

    await sendMessage(page, "long answer test");

    const aiMessage = page.getByTestId("onyx-ai-message").first();
    await expect(aiMessage).toContainText(
      "When delivered by the service worker",
      {
        timeout: 15000,
      }
    );
  });
});
