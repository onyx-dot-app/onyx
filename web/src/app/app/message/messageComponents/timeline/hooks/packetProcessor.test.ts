import {
  createInitialState,
  processPackets,
} from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";
import {
  Packet,
  PacketIdentity,
  TextItem,
  ToolItem,
} from "@/app/app/services/streamingModels";

import {
  groupStepsByTurn,
  transformItemGroups,
} from "@/app/app/message/messageComponents/timeline/transformers";
import { stepHasCollapsedStreamingContent } from "@/app/app/message/messageComponents/timeline/itemHelpers";

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

it("keeps intermediate text visible outside the timeline when the message calls tools", () => {
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
    })
  );
  state = processPackets(state, packets);
  expect(state.potentialDisplayGroups).toHaveLength(0);
  expect(state.toolGroups).toHaveLength(0);
  expect(state.narrationGroups[0]?.items[0]?.content).toMatchObject({
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
      second
    )
  );
  state = processPackets(state, packets);
  expect(
    state.toolGroups.map((group) => group.items[0]?.content.status)
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
      parent
    ),
    packet(
      {
        type: "item_update",
        item: { ...text, text: "Child response", purpose: "report" },
      },
      child
    ),
    packet(
      { type: "item_update", item: { ...tool, name: "think_tool" } },
      {
        ...identity,
        message_id: "control",
        part_id: "tool",
        tool_call_id: "think",
      }
    ),
  ]);
  expect(state.potentialDisplayGroups).toEqual([]);
  expect(state.toolGroups).toHaveLength(1);
  expect(state.toolGroups[0]?.items).toHaveLength(2);
});

it("removes an unaccepted preview without leaving an empty timeline step", () => {
  const packets = [
    packet({ type: "item_update", item: { ...text, text: "preview" } }),
  ];
  let state = processPackets(createInitialState(1), packets);
  expect(state.potentialDisplayGroups).toHaveLength(1);
  packets.push(
    packet({
      type: "item_update",
      item: { ...text, status: "complete", text: "" },
    })
  );
  state = processPackets(state, packets);
  expect(state.potentialDisplayGroups).toEqual([]);
  expect(state.toolGroups).toEqual([]);
});

it("keeps narration outside parallel tool tabs and opens previews only for visible content", () => {
  const narration = packet({
    type: "item_update",
    item: {
      ...text,
      text: "I will search and open the guide.",
      purpose: "commentary",
      status: "complete",
    },
  });
  const searchId = { ...identity, part_id: "tool", tool_call_id: "search" };
  const openId = { ...identity, part_id: "tool", tool_call_id: "open" };
  const search: ToolItem = {
    ...tool,
    name: "internal_search",
    arguments: { queries: [] },
    status: "pending",
  };
  const open: ToolItem = {
    ...tool,
    name: "open_url",
    arguments: { urls: [] },
    status: "pending",
  };
  const packets = [
    narration,
    packet({ type: "item_update", item: search }, searchId),
    packet({ type: "item_update", item: open }, openId),
  ];
  let state = processPackets(createInitialState(1), packets);
  let groups = groupStepsByTurn(transformItemGroups(state.toolGroups));
  expect(state.narrationGroups[0]?.items[0]?.content.kind).toBe("text");
  expect(groups).toHaveLength(1);
  expect(groups[0]?.isParallel).toBe(true);
  for (const step of groups[0]!.steps)
    expect(stepHasCollapsedStreamingContent(step.items)).toBe(false);

  packets.push(
    packet(
      {
        type: "item_update",
        item: {
          ...search,
          status: "running",
          arguments: { queries: ["Onyx architecture"] },
        },
      },
      searchId
    )
  );
  packets.push(
    packet(
      {
        type: "item_update",
        item: {
          ...open,
          status: "running",
          arguments: { urls: ["https://docs.onyx.app"] },
        },
      },
      openId
    )
  );
  state = processPackets(state, packets);
  groups = groupStepsByTurn(transformItemGroups(state.toolGroups));
  expect(stepHasCollapsedStreamingContent(groups[0]!.steps[0]!.items)).toBe(
    true
  );
  expect(stepHasCollapsedStreamingContent(groups[0]!.steps[1]!.items)).toBe(
    false
  );
});
