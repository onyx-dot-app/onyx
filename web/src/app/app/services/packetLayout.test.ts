import { PacketLayout } from "@/app/app/services/packetLayout";
import { Packet, PacketIdentity } from "@/app/app/services/streamingModels";
import {
  createInitialState,
  processPackets,
} from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";

function packet(
  identity: Partial<PacketIdentity>,
  content = "content"
): Packet {
  return {
    identity: {
      response_id: 12,
      run_id: "root",
      message_id: "root:0",
      part_id: "answer",
      ...identity,
    },
    obj: {
      type: "item_update",
      item: {
        kind: "text",
        text: content,
        purpose: "commentary",
        status: "running",
        documents: [],
        citations: [],
      },
    },
  };
}

function place(layout: PacketLayout, packet: Packet) {
  if (!packet.identity) throw new Error("Test packet requires identity");
  return layout.place(packet.identity, packet.model_index ?? 0);
}

test("narration and parallel tools keep distinct groups across live delivery and reload", () => {
  const packets = [
    packet({ part_id: "reasoning" }),
    packet({}),
    packet({ tool_call_id: "a", part_id: "tool" }),
    packet({ tool_call_id: "b", part_id: "tool" }),
    packet({ tool_call_id: "b", part_id: "tool" }, "progress"),
    packet({ tool_call_id: "a", part_id: "tool" }, "progress"),
    packet({ message_id: "root:1", tool_call_id: "a", part_id: "tool" }),
  ];
  const live = new PacketLayout();
  const projected = packets.map((item) => place(live, item));
  expect(projected).toEqual([
    { turn_index: 0, tab_index: 0, model_index: 0 },
    { turn_index: 1, tab_index: 0, model_index: 0 },
    { turn_index: 2, tab_index: 0, model_index: 0 },
    { turn_index: 2, tab_index: 1, model_index: 0 },
    { turn_index: 2, tab_index: 1, model_index: 0 },
    { turn_index: 2, tab_index: 0, model_index: 0 },
    { turn_index: 3, tab_index: 0, model_index: 0 },
  ]);
  const history = new PacketLayout();
  expect(packets.map((item) => place(history, item))).toEqual(projected);
});

test("children use the parent message and call identity despite reused provider IDs", () => {
  const layout = new PacketLayout();
  const first = place(
    layout,
    packet({ tool_call_id: "same", part_id: "tool" })
  );
  const second = place(
    layout,
    packet({ message_id: "root:1", tool_call_id: "same", part_id: "tool" })
  );
  const child = place(
    layout,
    packet({
      run_id: "child",
      message_id: "child:0",
      parent_run_id: "root",
      parent_message_id: "root:0",
      parent_tool_call_id: "same",
      tool_call_id: "leaf",
      part_id: "tool",
    })
  );
  const grandchild = place(
    layout,
    packet({
      run_id: "grandchild",
      message_id: "grandchild:0",
      parent_run_id: "child",
      parent_message_id: "child:0",
      parent_tool_call_id: "leaf",
    })
  );
  expect(child.turn_index).toBe(first.turn_index);
  expect(child.turn_index).not.toBe(second.turn_index);
  expect(grandchild.turn_index).toBe(first.turn_index);
  expect(grandchild.sub_turn_index).not.toBe(child.sub_turn_index);
  expect(child.model_index).toBe(0);
});

test("child completion does not stop the root timeline", () => {
  const progress = packet({});
  const childEnd: Packet = {
    ...packet({ run_id: "child", part_id: "run", parent_run_id: "root" }),
    obj: { type: "run_update", status: "complete" },
  };
  const state = createInitialState(12);
  processPackets(state, [progress, childEnd]);
  expect(state.stopPacketSeen).toBe(false);
  const rootEnd: Packet = {
    ...packet({ part_id: "run" }),
    obj: { type: "stop" },
  };
  processPackets(state, [progress, childEnd, rootEnd]);
  expect(state.stopPacketSeen).toBe(true);
});
