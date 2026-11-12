import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { resumeStream } from "@/app/app/services/lib";
import type { PendingChatMessage } from "@/lib/chat/types";

jest.mock("swr", () => ({ mutate: jest.fn() }));

function pending(id: string): PendingChatMessage {
  return { id, message: id, delivery: "send", target_response_id: 2 };
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
            new TextEncoder().encode(`${JSON.stringify(accepted)}\n`)
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
