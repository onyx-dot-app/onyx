import { PacketLayout } from "@/app/app/services/packetLayout";
import {
  Packet,
  PacketIdentity,
  PacketType,
} from "@/app/app/services/streamingModels";
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
    placement: { turn_index: 99 },
    obj: { type: PacketType.MESSAGE_DELTA, content },
  };
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
  const projected = packets.map((item) => live.project(item));
  expect(projected.map((item) => item.placement)).toEqual([
    { turn_index: 0, tab_index: 0, model_index: 0 },
    { turn_index: 1, tab_index: 0, model_index: 0 },
    { turn_index: 1, tab_index: 1, model_index: 0 },
    { turn_index: 1, tab_index: 2, model_index: 0 },
    { turn_index: 1, tab_index: 2, model_index: 0 },
    { turn_index: 1, tab_index: 1, model_index: 0 },
    { turn_index: 2, tab_index: 0, model_index: 0 },
  ]);
  const history = new PacketLayout();
  expect(packets.map((item) => history.project(item))).toEqual(projected);
});

test("children use the parent message and call identity despite reused provider IDs", () => {
  const layout = new PacketLayout();
  layout.setResponses([11, 12]);
  const first = layout.project(
    packet({ tool_call_id: "same", part_id: "tool" })
  );
  const second = layout.project(
    packet({ message_id: "root:1", tool_call_id: "same", part_id: "tool" })
  );
  const child = layout.project(
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
  const grandchild = layout.project(
    packet({
      run_id: "grandchild",
      message_id: "grandchild:0",
      parent_run_id: "child",
      parent_message_id: "child:0",
      parent_tool_call_id: "leaf",
    })
  );
  expect(child.placement.turn_index).toBe(first.placement.turn_index);
  expect(child.placement.turn_index).not.toBe(second.placement.turn_index);
  expect(grandchild.placement.turn_index).toBe(first.placement.turn_index);
  expect(grandchild.placement.sub_turn_index).not.toBe(
    child.placement.sub_turn_index
  );
  expect(child.placement.model_index).toBe(1);
});

test("child completion does not stop the root timeline", () => {
  const layout = new PacketLayout();
  const progress = packet({});
  const childEnd: Packet = {
    ...packet({ run_id: "child", part_id: "run", parent_run_id: "root" }),
    obj: { type: PacketType.OPERATION_STATUS, status: "complete" },
  };
  const state = createInitialState(12);
  processPackets(state, [layout.project(progress), layout.project(childEnd)]);
  expect(state.stopPacketSeen).toBe(false);
  const rootEnd: Packet = {
    ...packet({ part_id: "run" }),
    obj: { type: PacketType.STOP },
  };
  processPackets(state, [
    layout.project(progress),
    layout.project(childEnd),
    layout.project(rootEnd),
  ]);
  expect(state.stopPacketSeen).toBe(true);
});
