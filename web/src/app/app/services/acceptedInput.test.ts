import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { resumeStream } from "@/app/app/services/lib";
import type { PendingChatMessage } from "@/lib/chat/types";

jest.mock("swr", () => ({ mutate: jest.fn() }));

function pending(id: string): PendingChatMessage {
  return {
    id,
    message: id,
    delivery: "send",
    target_response_id: 2,
    deep_research: false,
    llm_override: null,
    mentions: [],
  };
}

test("a stream removes the pending input its turn accepts", async () => {
  const accepted = {
    placement: { turn_index: 1 },
    obj: { type: "user_message", id: "pending-1", message: "Use the report" },
  };
  jest.spyOn(global, "fetch").mockResolvedValue(
    new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(
            new TextEncoder().encode(
              `${JSON.stringify({ jsonrpc: "2.0", method: "_onyx/user_message", params: { sessionId: "chat", packet: accepted } })}\n`
            )
          );
          controller.close();
        },
      })
    )
  );

  for await (const _packet of resumeStream("chat", 3, 0)) {
    // Drain the stream.
  }

  const mockedMutate = jest.mocked(mutate);
  expect(mockedMutate).toHaveBeenCalledWith(
    SWR_KEYS.pendingChatMessages("chat"),
    expect.any(Function),
    { revalidate: false }
  );
  const remove = mockedMutate.mock.calls[0]![1] as (
    current: PendingChatMessage[] | undefined
  ) => PendingChatMessage[] | undefined;
  expect(remove([pending("pending-1"), pending("pending-2")])).toEqual([
    pending("pending-2"),
  ]);
});

test("one-byte reads render each Unicode chunk once and preserve the final unterminated notice", async () => {
  const placement = { turn_index: 1 };
  const frame = {
    jsonrpc: "2.0",
    method: "session/update",
    params: {
      sessionId: "chat",
      update: {
        sessionUpdate: "agent_message_chunk",
        content: { type: "text", text: "🌲" },
        _meta: { onyx: { placement } },
      },
    },
  };
  const stop = { placement, obj: { type: "stop", stop_reason: "finished" } };
  const ending = {
    jsonrpc: "2.0",
    method: "_onyx/stop",
    params: { sessionId: "chat", packet: stop },
  };
  const data = new TextEncoder().encode(
    JSON.stringify(frame) + "\n\n" + JSON.stringify(ending)
  );
  jest.spyOn(global, "fetch").mockResolvedValue(
    new Response(
      new ReadableStream({
        start(controller) {
          for (const byte of data) controller.enqueue(Uint8Array.of(byte));
          controller.close();
        },
      })
    )
  );
  const packets = [];
  for await (const packet of resumeStream("chat", 7, 0)) packets.push(packet);
  expect(packets).toEqual([
    { placement, obj: { type: "message_delta", content: "🌲" } },
    stop,
  ]);
});
