import { expect, it } from "@jest/globals";
import { createInitialState, processPackets } from "@/chat/messageProcessor";
import {
  Packet,
  PacketIdentity,
  TextItem,
  ToolItem,
} from "@/chat/streamingModels";

const identity: PacketIdentity = {
  response_id: 1,
  run_id: "root",
  message_id: "generation",
  part_id: "text",
};
const text: TextItem = {
  kind: "text",
  text: "",
  purpose: "answer",
  status: "running",
  citations: [],
  documents: [],
};
const tool: ToolItem = {
  kind: "tool",
  name: "web_search",
  arguments: { queries: ["question"] },
  status: "running",
  output: "",
  metadata: null,
};
function packet(obj: Packet["obj"], id = identity): Packet {
  return { identity: id, obj };
}

it("moves intermediate text into the timeline when the completed message calls tools", () => {
  const packets = [packet({ type: "item_update", item: text })];
  let state = processPackets(createInitialState(1), packets);
  expect(state.potentialDisplayGroups).toHaveLength(1);
  packets.push(
    packet({
      type: "item_update",
      item: {
        ...text,
        text: "Searching",
        purpose: "commentary",
        status: "complete",
      },
    }),
  );
  state = processPackets(state, packets);
  expect(state.potentialDisplayGroups).toHaveLength(0);
  expect(state.toolGroups[0]?.items[0]?.content).toMatchObject({
    text: "Searching",
    purpose: "commentary",
  });
});

it("uses explicit completion without finishing parallel tools from packet order", () => {
  const first = { ...identity, part_id: "tool", tool_call_id: "one" };
  const second = { ...identity, part_id: "tool", tool_call_id: "two" };
  const packets = [
    packet({ type: "item_update", item: tool }, first),
    packet({ type: "item_update", item: tool }, second),
  ];
  let state = processPackets(createInitialState(1), packets);
  packets.push(
    packet(
      { type: "item_update", item: { ...tool, status: "complete" } },
      second,
    ),
  );
  state = processPackets(state, packets);
  expect(
    state.toolGroups.map((group) => group.items[0]?.content.status),
  ).toEqual(["running", "complete"]);
});

it("live deltas and loaded complete items produce the same answer and citations", () => {
  const final: TextItem = {
    ...text,
    status: "complete",
    text: "Answer [1]",
    citations: [{ citation_number: 1, document_id: "source" }],
  };
  const live = processPackets(createInitialState(1), [
    packet({ type: "item_update", item: text }),
    packet({
      type: "item_delta",
      delta: { kind: "text", text: "Answer ", citations: [] },
    }),
    packet({
      type: "item_delta",
      delta: { kind: "text", text: "[1]", citations: final.citations },
    }),
    packet({ type: "item_update", item: final }),
  ]);
  const loaded = processPackets(createInitialState(1), [
    packet({ type: "item_update", item: final }),
  ]);
  expect(live.potentialDisplayGroups).toEqual(loaded.potentialDisplayGroups);
  expect(live.citations).toEqual(loaded.citations);
  expect(live.citationMap).toEqual({ 1: "source" });
});

it("keeps child output in its tool group and hides control tools", () => {
  const parent = { ...identity, part_id: "tool", tool_call_id: "research" };
  const child = {
    ...identity,
    run_id: "child",
    message_id: "child-message",
    parent_run_id: "root",
    parent_message_id: identity.message_id,
    parent_tool_call_id: "research",
  };
  const state = processPackets(createInitialState(1), [
    packet(
      { type: "item_update", item: { ...tool, name: "research_agent" } },
      parent,
    ),
    packet(
      {
        type: "item_update",
        item: { ...text, text: "Child response", purpose: "report" },
      },
      child,
    ),
    packet(
      { type: "item_update", item: { ...tool, name: "think_tool" } },
      {
        ...identity,
        message_id: "control",
        part_id: "tool",
        tool_call_id: "think",
      },
    ),
  ]);
  expect(state.potentialDisplayGroups).toEqual([]);
  expect(state.toolGroups).toHaveLength(1);
  expect(state.toolGroups[0]?.items).toHaveLength(2);
});

it("retains local parent placement when a resumed stream adds child output", () => {
  const parent = {
    ...identity,
    message_id: "parent",
    part_id: "tool",
    tool_call_id: "research",
  };
  const packets: Packet[] = [
    packet({
      type: "item_update",
      item: { ...text, text: "Checking", purpose: "commentary" },
    }),
    packet({ type: "item_update", item: tool }, parent),
  ];
  let state = processPackets(createInitialState(1), packets);
  const parentPlacement = state.toolGroups[1]?.items[0]?.placement;
  packets.push(
    packet(
      {
        type: "item_update",
        item: { ...text, text: "Child result", purpose: "report" },
      },
      {
        ...identity,
        run_id: "child",
        message_id: "child",
        parent_run_id: "root",
        parent_message_id: parent.message_id,
        parent_tool_call_id: "research",
      },
    ),
  );
  state = processPackets(state, packets);
  const group = state.toolGroups[1];
  expect(group?.items[0]?.placement).toEqual(parentPlacement);
  expect(group?.items[1]?.placement).toEqual({
    ...parentPlacement,
    sub_turn_index: 0,
  });
});
