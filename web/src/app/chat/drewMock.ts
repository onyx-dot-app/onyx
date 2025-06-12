import { PacketType, SendMessageParams } from "./lib";
import { buildActionPacket } from "./deepResearchAction";

export async function* mockSendMessage(
  params: SendMessageParams
): AsyncGenerator<PacketType, void, unknown> {
  // TODO: add aborthandler
  yield* mockSseStream(params);
}

function getRandomNumber(min: number, max: number) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

const delay = (ms: number) => {
  return new Promise((resolve) => setTimeout(resolve, ms));
};
async function* mockSseStream(
  _params: SendMessageParams
): AsyncGenerator<PacketType, void, unknown> {
  await delay(100);
  // Run server packet simulation here
  const userMessageId = getRandomNumber(1, 1000);

  yield {
    user_message_id: userMessageId,
    reserved_assistant_message_id: userMessageId + 1,
  };

  yield buildActionPacket("thinking", {
    id: "first-thinking",
    thinking: "thinking about the solute",
  });

  await delay(1000);
  yield {
    answer_piece: "Hello",
  };
  await delay(1000);
  yield {
    answer_piece: "World",
  };
}
