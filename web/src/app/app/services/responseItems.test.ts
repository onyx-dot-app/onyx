import {
  ResponseItems,
  interruptResponse,
} from "@/app/app/services/responseItems";
import {
  Packet,
  PacketIdentity,
  StopReason,
  ToolItem,
} from "@/app/app/services/streamingModels";

const identity: PacketIdentity = {
  response_id: 1,
  run_id: "root",
  message_id: "call",
  part_id: "tool",
  tool_call_id: "python-1",
};
const tool: ToolItem = {
  kind: "tool",
  name: "run_python",
  arguments: {},
  status: "pending",
  output: "",
  metadata: null,
};
function packet(obj: Packet["obj"], id = identity): Packet {
  return { identity: id, obj };
}

it("replaces tool output snapshots and preserves streamed arguments", () => {
  const state = new ResponseItems();
  state.apply(packet({ type: "item_update", item: tool }));
  state.apply(
    packet({
      type: "item_delta",
      delta: {
        kind: "tool_arguments",
        name: "run_python",
        arguments: { code: "print(" },
      },
    })
  );
  state.apply(
    packet({
      type: "item_delta",
      delta: {
        kind: "tool_arguments",
        name: "run_python",
        arguments: { code: '"hi")' },
      },
    })
  );
  state.apply(
    packet({ type: "item_delta", delta: { kind: "tool_output", output: "h" } })
  );
  state.apply(
    packet({ type: "item_delta", delta: { kind: "tool_output", output: "hi" } })
  );
  expect([...state.items.values()][0]?.content).toEqual({
    ...tool,
    arguments: { code: 'print("hi")' },
    output: "hi",
  });
  state.apply(
    packet({
      type: "item_update",
      item: {
        ...tool,
        status: "complete",
        output: "hi",
        arguments: { code: 'print("hi")' },
      },
    })
  );
  expect(state.items.size).toBe(1);
  expect([...state.items.values()][0]?.content.status).toBe("complete");
});

it("cancellation closes pending and active items only within its run", () => {
  const state = new ResponseItems();
  state.apply(packet({ type: "item_update", item: tool }));
  state.apply(
    packet(
      { type: "item_update", item: { ...tool, status: "running" } },
      { ...identity, run_id: "child", message_id: "other" }
    )
  );
  state.apply(packet({ type: "run_update", status: "cancelled" }));
  expect([...state.items.values()].map((item) => item.content.status)).toEqual([
    "cancelled",
    "running",
  ]);
});

it("root stops settle their response without changing another model or completed results", () => {
  const state = new ResponseItems();
  state.apply(packet({ type: "item_update", item: tool }));
  state.apply(
    packet(
      { type: "item_update", item: { ...tool, status: "error" } },
      { ...identity, message_id: "failed" }
    )
  );
  state.apply(
    packet({ type: "item_update", item: tool }, { ...identity, response_id: 2 })
  );
  state.apply(packet({ type: "stop", stop_reason: StopReason.USER_CANCELLED }));
  expect([...state.items.values()].map((item) => item.content.status)).toEqual([
    "cancelled",
    "error",
    "pending",
  ]);
  state.apply({
    obj: { type: "stop", stop_reason: StopReason.USER_CANCELLED },
  });
  expect([...state.items.values()].map((item) => item.content.status)).toEqual([
    "cancelled",
    "error",
    "cancelled",
  ]);
});

it("resumed child deltas retain the parent's layout from earlier delivery", () => {
  const state = new ResponseItems();
  state.apply(
    packet({
      type: "item_update",
      item: { ...tool, name: "research_agent", status: "running" },
    })
  );
  const childIdentity: PacketIdentity = {
    ...identity,
    run_id: "child",
    message_id: "child-message",
    part_id: "text",
    tool_call_id: null,
    parent_run_id: "root",
    parent_message_id: identity.message_id,
    parent_tool_call_id: identity.tool_call_id,
  };
  state.apply(
    packet(
      {
        type: "item_update",
        item: {
          kind: "text",
          text: "Partial",
          purpose: "report",
          status: "running",
          documents: [],
          citations: [],
        },
      },
      childIdentity
    )
  );
  state.apply(
    packet(
      {
        type: "item_delta",
        delta: { kind: "text", text: " resumed", citations: [] },
      },
      childIdentity
    )
  );
  const [parent, child] = [...state.items.values()];
  expect(child?.placement.turn_index).toBe(parent?.placement.turn_index);
  expect(child?.placement.sub_turn_index).toBe(0);
  expect(child?.content).toMatchObject({ text: "Partial resumed" });
});

it("settles interrupted cached work without changing completed tools or losing partial output", () => {
  const packets: Packet[] = [
    packet({
      type: "item_update",
      item: { ...tool, status: "complete", output: "kept result" },
    }),
    packet(
      {
        type: "item_update",
        item: { ...tool, status: "running", output: "partial output" },
      },
      { ...identity, tool_call_id: "unfinished" }
    ),
  ];
  const state = new ResponseItems();
  const snapshot = interruptResponse(packets);
  for (const update of snapshot) state.apply(update);
  expect([...state.items.values()].map((item) => item.content)).toEqual([
    { ...tool, status: "complete", output: "kept result" },
    { ...tool, status: "error", output: "partial output" },
  ]);
  expect(snapshot.at(-1)?.obj).toEqual({
    type: "stop",
    stop_reason: StopReason.INTERRUPTED,
  });
});
