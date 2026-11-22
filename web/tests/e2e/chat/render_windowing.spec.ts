import { test, expect } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import { ChatPage } from "@tests/e2e/chat/ChatPage";

const TURNS = 60;

interface SessionMessage {
  message_id: number;
  parent_message: number | null;
  latest_child_message: number | null;
  message_type: string;
  message: string;
}

interface Session {
  messages: SessionMessage[];
  packets: unknown[][];
}

function turnText(turn: number): string {
  return `Turn ${turn}. ${"A long question, so each row is tall. ".repeat(30)}`;
}

/**
 * The chat's saved first turn, repeated into `TURNS` turns: each question
 * says its turn number, and each reply replays the saved reply.
 */
function buildLongSession(saved: Session): Session {
  const root = saved.messages.find((m) => m.parent_message === null);
  const question = saved.messages.find((m) => m.message_type === "user");
  const reply = saved.messages.find((m) => m.message_type === "assistant");
  const replyPackets = saved.packets[0];
  if (!root || !question || !reply || !replyPackets) {
    throw new Error("The saved chat has no first turn to repeat");
  }

  const firstId = 1_000_000;
  const messages: SessionMessage[] = [
    { ...root, latest_child_message: firstId },
  ];
  for (let turn = 0; turn < TURNS; turn++) {
    const questionId = firstId + turn * 2;
    messages.push({
      ...question,
      message_id: questionId,
      parent_message: turn === 0 ? root.message_id : questionId - 1,
      latest_child_message: questionId + 1,
      message: turnText(turn + 1),
    });
    messages.push({
      ...reply,
      message_id: questionId + 1,
      parent_message: questionId,
      latest_child_message: turn === TURNS - 1 ? null : questionId + 2,
    });
  }
  return {
    ...saved,
    messages,
    packets: Array.from({ length: TURNS }, () => replyPackets),
  };
}

test.describe("Chat render windowing", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
  });

  test.afterEach(async ({ page }) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("a long chat opens at its end, mounts the rows near the viewport, and scrolls both ways", async ({
    page,
  }) => {
    const chat = new ChatPage(page);
    await sendMessage(page, "Start a chat to grow");
    const chatId = new URL(page.url()).searchParams.get("chatId");
    if (!chatId) throw new Error("The chat has no id");

    // Serve the chat as a long conversation built from its saved turn.
    await page.route(
      `**/api/chat/get-chat-session/${chatId}*`,
      async (route) => {
        const response = await route.fetch();
        const saved: Session = await response.json();
        await route.fulfill({ response, json: buildLongSession(saved) });
      }
    );
    await chat.goto(chatId);

    // Opens at the end.
    await expect(chat.humanMessages.last()).toContainText(`Turn ${TURNS}.`);
    await expect(chat.scrollToBottomButton).toBeHidden();

    // Every message has a row, but only those near the viewport are mounted.
    await expect(chat.messageRows).toHaveCount(TURNS * 2);
    await expect.poll(() => chat.humanMessages.count()).toBeLessThan(TURNS / 2);

    // The top of the chat mounts when scrolled to.
    await chat.scrollTo("top");
    await expect(chat.humanMessages.first()).toContainText("Turn 1.");

    // Scroll to bottom lands at the end.
    await chat.scrollToBottomButton.click();
    await expect(chat.scrollToBottomButton).toBeHidden();
    await expect(chat.humanMessages.last()).toContainText(`Turn ${TURNS}.`);
  });
});
