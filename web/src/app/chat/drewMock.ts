import { PacketType, SendMessageParams } from "./lib";
import { buildActionPacket } from "./deepResearchAction";
import { longHtml } from "./mockConstants";

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
    thinking: "Thinking about what makes a shoe good",
  });

  await delay(1000);

  yield buildActionPacket("web_search", {
    collapsed: false,
    id: "first-web-search",
    query: "Best shoes to buy",
    results: [],
  });
  await delay(1000);
  yield buildActionPacket("web_search", {
    collapsed: false,
    id: "first-web-search",
    query: "Best shoes to buy",
    results: [
      {
        title:
          "A place for runners to share running shoe related news, releases, reviews, and deals. Please use our sister sub r/",
        url: "https://www.reddit.com/r/RunningShoeGeeks",
      },
    ],
  });
  await delay(1000);
  yield buildActionPacket("web_search", {
    collapsed: false,
    id: "first-web-search",
    query: "Best shoes to buy",
    results: [
      {
        title: "(Reddit) Shoe Reviews",
        url: "https://www.reddit.com/r/ShoeReviews/",
      },
      {
        title: "Nike. Just Do It. Nike.com",
        url: "https://www.nike.com/",
      },
    ],
  });

  await delay(200);
  yield buildActionPacket("run_command", {
    id: "parse-nike",
    cmd: `curl https://www.nike.com/`,
    collapsed: false,
    result: "",
  });

  await delay(200);
  yield buildActionPacket("run_command", {
    id: "parse-reddit",
    cmd: `curl https://www.reddit.com/r/RunningShoeGeeks`,
    result: longHtml,
    collapsed: false,
  });
  await delay(200);
  await delay(200);
  yield buildActionPacket("run_command", {
    id: "parse-nike",
    cmd: `curl https://www.nike.com/`,
    result: longHtml,
    collapsed: false,
  });
  await delay(2000);
  yield buildActionPacket("run_command", {
    id: "parse-nike",
    cmd: `curl https://www.nike.com/`,
    result: longHtml,
    collapsed: true,
  });
  yield buildActionPacket("run_command", {
    id: "parse-reddit",
    cmd: `curl https://www.reddit.com/r/RunningShoeGeeks`,
    result: longHtml,
    collapsed: true,
  });
  yield buildActionPacket("process", {
    id: "think-curl-result",
    done: false,
    description: "Parsing web content",
  });
  await delay(4000);
  yield buildActionPacket("process", {
    id: "think-curl-result",
    done: true,
    description: "Parsing web content",
  });

  const finalAnswer = "This is a final answer. All shoes are good";
  const words = finalAnswer.split(" ");

  for (const word of words) {
    await delay(200);
    yield {
      answer_piece: word + " ",
    };
  }
}
