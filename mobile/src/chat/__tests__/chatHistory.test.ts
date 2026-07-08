import { describe, expect, it } from "@jest/globals";

import { processRawChatHistory } from "@/chat/chatHistory";
import { BackendMessage } from "@/chat/interfaces";
import { getLatestMessageChain } from "@/chat/messageTree";
import { MessageDelta, Packet } from "@/chat/streamingModels";

function bm(
  partial: Pick<
    BackendMessage,
    "message_id" | "message_type" | "parent_message"
  > &
    Partial<BackendMessage>,
): BackendMessage {
  return {
    latest_child_message: null,
    message: "",
    files: [],
    time_sent: "2026-06-29T00:00:00Z",
    error: null,
    ...partial,
  };
}

function packet(content: string): Packet {
  return {
    placement: { turn_index: 0 },
    obj: { type: "message_delta", content } as MessageDelta,
  };
}

describe("processRawChatHistory", () => {
  const raw: BackendMessage[] = [
    {
      ...bm({ message_id: 1, message_type: "user", parent_message: null }),
      message: "q1",
      latest_child_message: 2,
    },
    {
      ...bm({ message_id: 2, message_type: "assistant", parent_message: 1 }),
      message: "a1",
      latest_child_message: 3,
    },
    {
      ...bm({ message_id: 3, message_type: "user", parent_message: 2 }),
      message: "q2",
      latest_child_message: 4,
    },
    {
      ...bm({ message_id: 4, message_type: "assistant", parent_message: 3 }),
      message: "a2",
    },
  ];
  const packets: Packet[][] = [[packet("a0")], [packet("a1")]];

  it("uses message_id as nodeId and carries core fields", () => {
    const tree = processRawChatHistory(raw, packets);
    const m2 = tree.get(2)!;
    expect(m2.nodeId).toBe(2);
    expect(m2.messageId).toBe(2);
    expect(m2.type).toBe("assistant");
    expect(m2.message).toBe("a1");
    expect(m2.parentNodeId).toBe(1);
    expect(m2.latestChildNodeId).toBe(3);
  });

  it("populates and sorts childrenNodeIds from parent links", () => {
    const tree = processRawChatHistory(raw, packets);
    expect(tree.get(1)!.childrenNodeIds).toEqual([2]);
    expect(tree.get(2)!.childrenNodeIds).toEqual([3]);
    expect(tree.get(4)!.childrenNodeIds).toEqual([]);
  });

  it("aligns packet lists to assistant messages by ordinal", () => {
    const tree = processRawChatHistory(raw, packets);
    expect((tree.get(2)!.packets[0]!.obj as MessageDelta).content).toBe("a0");
    expect((tree.get(4)!.packets[0]!.obj as MessageDelta).content).toBe("a1");
  });

  it("maps an errored message to the error type", () => {
    const tree = processRawChatHistory(
      [
        bm({
          message_id: 9,
          message_type: "assistant",
          parent_message: null,
          error: "boom",
        }),
      ],
      [],
    );
    expect(tree.get(9)!.type).toBe("error");
  });

  it("produces a tree the chain walker can traverse (no system root needed)", () => {
    const tree = processRawChatHistory(raw, packets);
    expect(getLatestMessageChain(tree).map((m) => m.nodeId)).toEqual([
      1, 2, 3, 4,
    ]);
  });

  it("handles the leading SYSTEM root row that real get-chat-session payloads include", () => {
    // get-chat-session always serializes the persisted system root first
    // (message_type "system", parent_message null) — it must not derail the tree.
    const withSystem: BackendMessage[] = [
      {
        ...bm({
          message_id: 1000,
          message_type: "system",
          parent_message: null,
        }),
        latest_child_message: 1001,
      },
      {
        ...bm({ message_id: 1001, message_type: "user", parent_message: 1000 }),
        message: "q",
        latest_child_message: 1002,
      },
      {
        ...bm({
          message_id: 1002,
          message_type: "assistant",
          parent_message: 1001,
        }),
        message: "a",
      },
    ];
    const tree = processRawChatHistory(withSystem, [[packet("a0")]]);

    expect(tree.get(1000)!.type).toBe("system");
    // system root is present but excluded from the visible chain
    expect(getLatestMessageChain(tree).map((m) => m.nodeId)).toEqual([
      1001, 1002,
    ]);
    // assistant alignment survives the leading non-assistant rows
    expect((tree.get(1002)!.packets[0]!.obj as MessageDelta).content).toBe(
      "a0",
    );
  });

  it("tolerates missing packets for a message", () => {
    const tree = processRawChatHistory(
      [bm({ message_id: 1, message_type: "assistant", parent_message: null })],
      [],
    );
    expect(tree.get(1)!.packets).toEqual([]);
  });
});
