import savedResponse from "@/app/app/services/__fixtures__/savedResponse.json";
import { ResponseItems, itemKey } from "@/app/app/services/responseItems";
import { ChatItem } from "@/app/app/services/streamingModels";
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

test("live completion order and saved tree order produce the same visible items", () => {
  const update = (
    identity: Partial<PacketIdentity>,
    item: ChatItem
  ): Packet => ({
    ...packet(identity),
    obj: { type: "item_update", item },
  });
  const text = (
    value: string,
    purpose: "answer" | "commentary" = "answer",
    status: "running" | "complete" = "complete"
  ): ChatItem => ({
    kind: "text",
    text: value,
    purpose,
    status,
    documents: [],
    citations: [],
  });
  const tool = (
    name: string,
    args: Record<string, string>,
    output = "",
    status: "running" | "complete" = "running"
  ): ChatItem => ({
    kind: "tool",
    name,
    arguments: args,
    output,
    status,
    metadata: null,
  });
  const a = { tool_call_id: "a", part_id: "tool" };
  const b = { tool_call_id: "b", part_id: "tool" };
  const child = (call: string): Partial<PacketIdentity> => ({
    run_id: `child-${call}`,
    message_id: `child-${call}:0`,
    parent_run_id: "root",
    parent_message_id: "root:0",
    parent_tool_call_id: call,
  });
  const live: Packet[] = [
    update(
      { part_id: "reasoning" },
      { kind: "reasoning", text: "Consider sources", status: "complete" }
    ),
    update({}, text("Checking both sources.", "answer", "running")),
    update(a, tool("research_agent", { query: "first" })),
    update(b, tool("research_agent", { query: "second" })),
    // The second child finishes first. History instead walks the first tool's subtree first.
    update(child("b"), text("Source ", "answer", "running")),
    {
      ...packet(child("b")),
      obj: {
        type: "item_delta",
        delta: { kind: "text", text: "b", citations: [] },
      },
    },
    { ...packet(child("b")), obj: { type: "run_update", status: "complete" } },
    update(
      b,
      tool("research_agent", { query: "second" }, "Second source", "complete")
    ),
    update(child("a"), text("Source a")),
    update(
      a,
      tool("research_agent", { query: "first" }, "First source", "complete")
    ),
    update({}, text("Checking both sources.", "commentary")),
    // Provider call IDs can repeat in a later message.
    update(
      { ...a, message_id: "root:1" },
      tool("open_url", { url: "https://example.com" })
    ),
    update(
      { ...a, message_id: "root:1" },
      tool("open_url", { url: "https://example.com" }, "Verified", "complete")
    ),
    update({ message_id: "root:2" }, text("The final ", "answer", "running")),
    {
      ...packet({ message_id: "root:2" }),
      obj: {
        type: "item_delta",
        delta: { kind: "text", text: "answer.", citations: [] },
      },
    },
    {
      ...packet({ part_id: "run" }),
      obj: { type: "run_update", status: "complete" },
    },
    { obj: { type: "stop" } },
  ];
  const project = (packets: Packet[]) => {
    const state = new ResponseItems();
    packets.forEach((event) => state.apply(event));
    return [...state.items.values()]
      .map((item) => ({
        key: itemKey(item),
        placement: item.placement,
        kind: item.content.kind,
        status: item.content.status,
        text:
          item.content.kind === "tool"
            ? item.content.output
            : item.content.text,
        purpose:
          item.content.kind === "text" ? item.content.purpose : undefined,
        arguments:
          item.content.kind === "tool" ? item.content.arguments : undefined,
      }))
      .sort((left, right) => left.key.localeCompare(right.key));
  };
  const liveItems = project(live);
  expect(liveItems).toHaveLength(8);
  // SAFETY: The fixture generator serializes backend-validated Packet models.
  expect(liveItems).toEqual(project(savedResponse as Packet[]));
  expect(
    liveItems.filter((item) => item.placement.sub_turn_index !== undefined)
  ).toHaveLength(2);
  expect(
    liveItems
      .filter((item) => item.kind === "tool")
      .map((item) => item.placement)
  ).toEqual([
    { turn_index: 2, tab_index: 0, model_index: 0 },
    { turn_index: 2, tab_index: 1, model_index: 0 },
    { turn_index: 3, tab_index: 0, model_index: 0 },
  ]);
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
