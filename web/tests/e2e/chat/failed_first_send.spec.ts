import { test } from "@tests/e2e/chat/fixtures";
import { mockChatEndpoint } from "@tests/e2e/utils/chatMock";

// A stream that fails before the server takes the turn saves nothing.
const REJECTED_STREAM = `${JSON.stringify({ error: "simulated rejection" })}\n`;

test.describe("A failed first send in a new chat", () => {
  test("gives the typed message back for a retry", async ({ chatPage }) => {
    await chatPage.goto();
    await mockChatEndpoint(chatPage.page, REJECTED_STREAM);

    await chatPage.inputBar.fill("restore me");
    await chatPage.inputBar.send();

    await chatPage.inputBar.expectText("restore me");
  });
});
