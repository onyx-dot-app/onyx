import {
  Packet,
  PacketType,
  PydanticStreamEvent,
} from "@/app/app/services/streamingModels";
import {
  getTextContent,
  isActualToolCallPacket,
  isFinalAnswerComplete,
} from "@/app/app/services/packetUtils";
import { nativeContent } from "@/app/app/services/pydanticEvents";
import {
  createInitialState,
  processPackets,
} from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";

function packet(event: PydanticStreamEvent, turn_index = 0): Packet {
  return {
    placement: { turn_index },
    obj: { type: PacketType.PYDANTIC_AI, event },
  };
}

test("renders native text once across start, delta, and complete-part events", () => {
  const packets = [
    packet({
      event_kind: "part_start",
      index: 0,
      part: { part_kind: "text", content: "Hello" },
    }),
    packet({
      event_kind: "part_delta",
      index: 0,
      delta: { part_delta_kind: "text", content_delta: " world" },
    }),
    packet({
      event_kind: "part_end",
      index: 0,
      part: { part_kind: "text", content: "Hello world" },
    }),
  ];
  expect(getTextContent(packets)).toBe("Hello world");
  const state = processPackets(createInitialState(1), packets);
  expect(state.potentialDisplayGroups).toHaveLength(1);
  expect(state.finalAnswerComing).toBe(true);
  expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(true);
});

test("keeps native thinking in its own timeline group without duplicating content", () => {
  const thinking = packet({
    event_kind: "part_start",
    index: 0,
    part: { part_kind: "thinking", content: "Checking sources" },
  });
  const end = packet({
    event_kind: "part_end",
    index: 0,
    part: { part_kind: "thinking", content: "Checking sources" },
  });
  const answer = packet(
    {
      event_kind: "part_start",
      index: 1,
      part: { part_kind: "text", content: "Answer" },
    },
    1
  );
  const state = processPackets(createInitialState(1), [thinking, end, answer]);
  expect(state.toolGroups).toHaveLength(1);
  expect(state.potentialDisplayGroups).toHaveLength(1);
  expect(
    nativeContent(thinking, "thinking") + nativeContent(end, "thinking")
  ).toBe("Checking sources");
  expect(isActualToolCallPacket(thinking)).toBe(false);
});

test("incremental processing retains native events and closes a group on cancellation", () => {
  const packets: Packet[] = [
    packet({
      event_kind: "part_start",
      index: 0,
      part: { part_kind: "text", content: "Partial" },
    }),
  ];
  const state = processPackets(createInitialState(1), packets);
  packets.push({
    placement: { turn_index: 0 },
    obj: { type: PacketType.ERROR, message: "Cancelled" },
  });
  const updated = processPackets(state, packets);
  expect(getTextContent(updated.potentialDisplayGroups[0]?.packets ?? [])).toBe(
    "Partial"
  );
  expect(updated.groupKeysWithSectionEnd.has("0-0")).toBe(true);
});

test("research report events stay in the tool group until its section ends", () => {
  const start: Packet = {
    placement: { turn_index: 1, tab_index: 0 },
    obj: {
      type: PacketType.RESEARCH_AGENT_START,
      research_task: "Check sources",
    },
  };
  const report: Packet = {
    placement: { turn_index: 1, tab_index: 0, sub_turn_index: 2 },
    obj: {
      type: PacketType.PYDANTIC_AI,
      phase: "report",
      event: {
        event_kind: "part_start",
        index: 0,
        part: { part_kind: "text", content: "Findings" },
      },
    },
  };
  const end: Packet = {
    ...report,
    obj: {
      type: PacketType.PYDANTIC_AI,
      phase: "report",
      event: {
        event_kind: "part_end",
        index: 0,
        part: { part_kind: "text", content: "Findings" },
      },
    },
  };
  const state = processPackets(createInitialState(1), [start, report, end]);
  expect(state.toolGroups).toHaveLength(1);
  expect(state.potentialDisplayGroups).toHaveLength(0);
  expect(state.finalAnswerComing).toBe(false);
  expect(state.groupKeysWithSectionEnd.has("1-0")).toBe(false);
});

test("copy, speech, and final display exclude research narration and child reports", () => {
  const text = (
    content: string,
    phase: "research" | "report",
    child: boolean
  ): Packet => ({
    placement: {
      turn_index: child ? 1 : phase === "research" ? 0 : 2,
      ...(child ? { sub_turn_index: 3 } : {}),
    },
    obj: {
      type: PacketType.PYDANTIC_AI,
      phase,
      event: {
        event_kind: "part_start",
        index: 0,
        part: { part_kind: "text", content },
      },
    },
  });
  const packets = [
    text("Searching sources", "research", false),
    text("Child findings", "report", true),
    text("Final answer", "report", false),
  ];
  expect(getTextContent(packets)).toBe("Final answer");
  const state = processPackets(createInitialState(1), packets);
  expect(state.potentialDisplayGroups).toHaveLength(1);
  expect(getTextContent(state.potentialDisplayGroups[0]?.packets ?? [])).toBe(
    "Final answer"
  );
  expect(state.toolGroups).toHaveLength(1);
});

test("native tool lifecycle before domain start does not hide or prematurely complete the group", () => {
  const call: Packet = packet({
    event_kind: "part_start",
    index: 0,
    part: {
      part_kind: "tool-call",
      tool_name: "search",
      tool_call_id: "call-1",
      args: {},
    },
  });
  const end = packet({
    event_kind: "part_end",
    index: 0,
    part: {
      part_kind: "tool-call",
      tool_name: "search",
      tool_call_id: "call-1",
      args: {},
    },
  });
  const started: Packet = {
    placement: { turn_index: 0 },
    obj: {
      type: PacketType.RESEARCH_AGENT_START,
      research_task: "Sources",
    },
  };
  const state = processPackets(createInitialState(1), [call, end, started]);
  expect(state.toolGroups).toHaveLength(1);
  expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(false);
});

test("native final answer completes on its own text part end", () => {
  const start = packet({
    event_kind: "part_start",
    index: 0,
    part: { part_kind: "text", content: "Answer" },
  });
  const end = packet({
    event_kind: "part_end",
    index: 0,
    part: { part_kind: "text", content: "Answer" },
  });
  expect(isFinalAnswerComplete([start])).toBe(false);
  expect(
    isFinalAnswerComplete([
      start,
      { ...end, placement: { turn_index: 0, tab_index: 1 } },
    ])
  ).toBe(false);
  expect(isFinalAnswerComplete([start, end])).toBe(true);
});
