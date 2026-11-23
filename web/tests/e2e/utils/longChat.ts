import type { Page } from "@playwright/test";

/** How many turns `serveLongChat` gives a chat. */
export const LONG_CHAT_TURNS = 60;

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
 * The chat's saved first turn, repeated into `LONG_CHAT_TURNS` turns: each question
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
  for (let turn = 0; turn < LONG_CHAT_TURNS; turn++) {
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
      latest_child_message:
        turn === LONG_CHAT_TURNS - 1 ? null : questionId + 2,
    });
  }
  return {
    ...saved,
    messages,
    packets: Array.from({ length: LONG_CHAT_TURNS }, () => replyPackets),
  };
}

/**
 * Serves the chat `chatId` as a long conversation built from its saved first
 * turn: each question says its turn number ("Turn 1." ...), and each reply
 * replays the saved reply.
 */
export async function serveLongChat(page: Page, chatId: string): Promise<void> {
  await page.route(`**/api/chat/get-chat-session/${chatId}*`, async (route) => {
    const response = await route.fetch();
    const saved: Session = await response.json();
    await route.fulfill({ response, json: buildLongSession(saved) });
  });
}
