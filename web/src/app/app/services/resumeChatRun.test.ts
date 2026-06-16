import { Message, RetrievalType } from "@/app/app/interfaces";
import {
  applyResumedPacketsToMessageTree,
  PacketType as StreamPacket,
} from "@/app/app/services/lib";
import { Packet, PacketType } from "@/app/app/services/streamingModels";

function assistantMessage(overrides: Partial<Message> = {}): Message {
  return {
    nodeId: 42,
    messageId: 42,
    message: "Message is loading... Please refresh the page soon.",
    type: "assistant",
    files: [],
    toolCall: null,
    parentNodeId: 41,
    packets: [],
    retrievalType: RetrievalType.None,
    ...overrides,
  };
}

function packet(type: PacketType, obj: Record<string, unknown>): Packet {
  return {
    placement: { turn_index: 0, tab_index: 0 },
    obj: { type, ...obj } as Packet["obj"],
  };
}

describe("applyResumedPacketsToMessageTree", () => {
  it("rebuilds visible assistant text from replayed message deltas", () => {
    const messageTree = new Map<number, Message>([[42, assistantMessage()]]);

    const updated = applyResumedPacketsToMessageTree(messageTree, 42, [
      packet(PacketType.MESSAGE_DELTA, { content: "hello " }),
      packet(PacketType.MESSAGE_DELTA, { content: "world" }),
      packet(PacketType.STOP, {}),
    ]);

    const message = updated.get(42)!;
    expect(message.message).toBe("hello world");
    expect(message.type).toBe("assistant");
    expect(message.is_generating).toBe(false);
    expect(message.packetCount).toBe(3);
    expect(message.packets).toHaveLength(3);
  });

  it("turns resumed streaming errors into error messages", () => {
    const messageTree = new Map<number, Message>([[42, assistantMessage()]]);

    const updated = applyResumedPacketsToMessageTree(messageTree, 42, [
      { error: "provider failed", stack_trace: "trace", is_retryable: true },
    ] satisfies StreamPacket[]);

    const message = updated.get(42)!;
    expect(message.message).toBe("provider failed");
    expect(message.type).toBe("error");
    expect(message.stackTrace).toBe("trace");
    expect(message.isRetryable).toBe(true);
    expect(message.is_generating).toBe(false);
  });
});
