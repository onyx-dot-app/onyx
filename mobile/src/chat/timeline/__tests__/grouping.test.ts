import { describe, expect, it } from "@jest/globals";

import {
  createInitialState,
  processPackets,
  type GroupedPacket,
  type ProcessedMessageState,
} from "@/chat/messageProcessor";
import {
  PacketType,
  type Packet,
  type Placement,
} from "@/chat/streamingModels";

import { isToolComplete } from "@/chat/timeline/toolDisplay";

import { makePlacedPacket } from "../../__tests__/fixtures";
import { isCodingAgentPackets } from "../packetHelpers";

const reasoningStart = (turn: number, tab = 0): Packet =>
  makePlacedPacket(
    { type: "reasoning_start" },
    { turn_index: turn, tab_index: tab },
  );
const reasoningDelta = (text: string, turn: number, tab = 0): Packet =>
  makePlacedPacket(
    { type: "reasoning_delta", reasoning: text },
    { turn_index: turn, tab_index: tab },
  );
const searchStart = (turn: number, tab = 0, internet = false): Packet =>
  makePlacedPacket(
    { type: "search_tool_start", is_internet_search: internet },
    { turn_index: turn, tab_index: tab },
  );
const sectionEnd = (turn: number, tab = 0): Packet =>
  makePlacedPacket(
    { type: "section_end" },
    { turn_index: turn, tab_index: tab },
  );
const messageStart = (turn: number, preSeconds?: number): Packet =>
  makePlacedPacket(
    {
      type: "message_start",
      id: "m",
      content: "",
      final_documents: null,
      ...(preSeconds !== undefined
        ? { pre_answer_processing_seconds: preSeconds }
        : {}),
    },
    { turn_index: turn },
  );
const stopAt = (turn: number): Packet =>
  makePlacedPacket({ type: "stop" }, { turn_index: turn });
const searchQueriesDelta = (turn: number, tab = 0): Packet =>
  makePlacedPacket(
    { type: "search_tool_queries_delta", queries: ["q"] },
    { turn_index: turn, tab_index: tab },
  );

const codeModeStart = (turn: number): Packet =>
  makePlacedPacket(
    { type: "code_mode_start", code: "await search(query='x')" },
    { turn_index: turn },
  );
const imageFinal = (fileIds: string[], placement: Partial<Placement>): Packet =>
  makePlacedPacket(
    {
      type: "image_generation_final",
      images: fileIds.map((file_id) => ({
        file_id,
        url: "u",
        revised_prompt: "p",
      })),
    },
    placement,
  );

function run(packets: Packet[]): ProcessedMessageState {
  return processPackets(createInitialState(1), packets);
}

const keyOf = (g: GroupedPacket) => `${g.turn_index}-${g.tab_index}`;
const hasSectionEnd = (state: ProcessedMessageState, key: string) =>
  (state.groupedPacketsMap.get(key) ?? []).some(
    (p) => p.obj.type === PacketType.SECTION_END,
  );

describe("grouping engine", () => {
  it("groups packets into tool steps by turn/tab and sorts them", () => {
    const state = run([
      reasoningStart(1),
      reasoningStart(0),
      reasoningDelta("thinking", 0),
    ]);
    expect(state.toolGroups.map(keyOf)).toEqual(["0-0", "1-0"]);
  });

  it("synthesizes SECTION_END into a prior group when a new turn_index starts", () => {
    const state = run([
      reasoningStart(0),
      reasoningDelta("hi", 0),
      reasoningStart(1),
    ]);
    expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    expect(hasSectionEnd(state, "0-0")).toBe(true);
    expect(state.groupKeysWithSectionEnd.has("1-0")).toBe(false);
  });

  it("does NOT close a sibling when only tab_index changes within a turn", () => {
    const state = run([searchStart(0, 0), searchStart(0, 1)]);
    expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(false);
    expect(state.groupKeysWithSectionEnd.has("0-1")).toBe(false);
    expect(state.toolGroups.map(keyOf).sort()).toEqual(["0-0", "0-1"]);
  });

  it("reaches a fully-closed, stopped end-state (via turn transitions + stop)", () => {
    const state = run([reasoningStart(0), searchStart(1), stopAt(2)]);
    expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    expect(state.groupKeysWithSectionEnd.has("1-0")).toBe(true);
    expect(state.stopPacketSeen).toBe(true);
    expect(state.isComplete).toBe(true);
  });

  it("stop closes an open group in the SAME turn (only the stop loop can close it)", () => {
    // No later turn fires the turn-transition path, so only the stop loop can close this group.
    const state = run([messageStart(0), stopAt(0)]);
    expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    expect(hasSectionEnd(state, "0-0")).toBe(true);
  });

  it("treats a real SECTION_END as completion without synthesizing a duplicate", () => {
    const state = run([
      reasoningStart(0),
      reasoningDelta("x", 0),
      sectionEnd(0),
    ]);
    expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    const ends = (state.groupedPacketsMap.get("0-0") ?? []).filter(
      (p) => p.obj.type === PacketType.SECTION_END,
    );
    expect(ends).toHaveLength(1);
  });

  it("drops TOP_LEVEL_BRANCHING sent by older servers", () => {
    const state = run([
      makePlacedPacket(
        { type: "top_level_branching", num_parallel_branches: 2 },
        { turn_index: 0 },
      ),
      searchStart(0, 0),
      searchStart(0, 1),
    ]);
    expect(state.groupedPacketsMap.has("0-0")).toBe(true);
    expect(state.toolGroups.map(keyOf).sort()).toEqual(["0-0", "0-1"]);
  });

  it("categorizes tool vs display groups", () => {
    const state = run([reasoningStart(0), messageStart(1)]);
    expect(state.toolGroupKeys.has("0-0")).toBe(true);
    expect(state.displayGroupKeys.has("1-0")).toBe(true);
    expect(state.potentialDisplayGroups.map(keyOf)).toEqual(["1-0"]);
  });

  it("sets finalAnswerComing on message_start and captures processing duration", () => {
    const state = run([reasoningStart(0), messageStart(1, 3.5)]);
    expect(state.finalAnswerComing).toBe(true);
    expect(state.toolProcessingDuration).toBe(3.5);
  });

  it("resets finalAnswerComing when a real tool call follows the message (Claude workaround)", () => {
    const state = run([messageStart(0), searchStart(1)]);
    expect(state.finalAnswerComing).toBe(false);
  });

  it("resets finalAnswerComing when a tool whose arguments streamed before the message starts", () => {
    const argsFirst = [
      makePlacedPacket(
        {
          type: "tool_call_argument_delta",
          tool_id: "call-1",
          tool_type: "python",
          argument_deltas: { code: "print(1)" },
        },
        { turn_index: 0 },
      ),
      messageStart(1),
    ];
    expect(run(argsFirst).finalAnswerComing).toBe(true);
    const started = run([
      ...argsFirst,
      makePlacedPacket(
        { type: "python_tool_start", code: "print(1)" },
        { turn_index: 0 },
      ),
    ]);
    expect(started.finalAnswerComing).toBe(false);
  });

  it("ends each open nested call on Stop, since nothing follows it", () => {
    const state = run([
      codeModeStart(0),
      makePlacedPacket(
        { type: "custom_tool_start", tool_name: "lookup" },
        { turn_index: 0, sub_turn_index: 0 },
      ),
      stopAt(1),
    ]);
    expect(state.toolGroups[0]?.nestedCalls[0]?.complete).toBe(true);
  });

  it("does NOT reset finalAnswerComing for reasoning after the message", () => {
    const state = run([messageStart(0), reasoningStart(1)]);
    expect(state.finalAnswerComing).toBe(true);
  });

  it("filters out a categorized tool group that has no content packet", () => {
    // "0-0" enters toolGroupKeys (queries_delta is a tool packet) but has no *_START content, so
    // hasContentPackets drops it — this exercises the content filter, not key categorization.
    const state = run([searchQueriesDelta(0), searchStart(1)]);
    expect(state.toolGroupKeys.has("0-0")).toBe(true);
    expect(state.toolGroups.map(keyOf)).toEqual(["1-0"]);
  });

  it("tolerates a non-zero model_index (groups by turn/tab only)", () => {
    const state = run([
      makePlacedPacket(
        { type: "reasoning_start" },
        { turn_index: 0, tab_index: 0, model_index: 1 },
      ),
      reasoningDelta("x", 0),
    ]);
    expect(state.toolGroups.map(keyOf)).toEqual(["0-0"]);
  });

  it("treats image generation as a tool step and collects its images once", () => {
    const state = run([
      makePlacedPacket({ type: "image_generation_start" }, { turn_index: 0 }),
      imageFinal(["a", "a", "b"], { turn_index: 0 }),
      sectionEnd(0),
      searchStart(1),
      sectionEnd(1),
      messageStart(2),
    ]);
    expect(state.toolGroups.map(keyOf)).toEqual(["0-0", "1-0"]);
    expect(state.potentialDisplayGroups.map(keyOf)).toEqual(["2-0"]);
    expect(state.generatedImages.map((i) => i.file_id)).toEqual(["a", "b"]);
    expect(state.finalAnswerComing).toBe(true);
  });

  it("does not start the answer on an image generation start", () => {
    const state = run([
      makePlacedPacket({ type: "image_generation_start" }, { turn_index: 0 }),
    ]);
    expect(state.finalAnswerComing).toBe(false);
    expect(state.displayGroupKeys.size).toBe(0);
  });

  it("collects nested images once per file_id", () => {
    const nested = { turn_index: 0, sub_turn_index: 0 };
    const state = run([
      codeModeStart(0),
      makePlacedPacket({ type: "image_generation_start" }, nested),
      imageFinal(["a"], nested),
      imageFinal(["a", "b"], { turn_index: 0 }),
    ]);
    expect(state.generatedImages.map((i) => i.file_id)).toEqual(["a", "b"]);
    expect(state.finalAnswerComing).toBe(false);
  });

  it("keeps a code mode step open until its parent SECTION_END", () => {
    const nested = { turn_index: 0, sub_turn_index: 0 };
    const open = run([
      codeModeStart(0),
      makePlacedPacket({ type: "search_tool_start" }, nested),
      makePlacedPacket({ type: "section_end" }, nested),
    ]);
    expect(open.toolGroups.map(keyOf)).toEqual(["0-0"]);
    expect(open.groupKeysWithSectionEnd.has("0-0")).toBe(false);
    const openPackets = open.toolGroups[0]?.packets ?? [];
    expect(isToolComplete(openPackets)).toBe(false);

    const closed = run([
      codeModeStart(0),
      makePlacedPacket({ type: "search_tool_start" }, nested),
      makePlacedPacket({ type: "section_end" }, nested),
      sectionEnd(0),
    ]);
    expect(closed.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    expect(isToolComplete(closed.toolGroups[0]?.packets ?? [])).toBe(true);
  });

  describe("a code mode cell's closing record after the answer", () => {
    const cell = { turn_index: 0 };
    const runningObservation: Packet[] = [
      makePlacedPacket(
        {
          type: "code_mode_start",
          code: "print(1)",
          cell_id: null,
          observation: 0,
        },
        cell,
      ),
      makePlacedPacket(
        {
          type: "code_mode_delta",
          stdout: "1\n",
          status: "running",
          cell_id: 1,
          observation: 0,
        },
        cell,
      ),
      sectionEnd(0),
    ];
    const closingRecord: Packet[] = [
      makePlacedPacket(
        { type: "image_generation_start" },
        { ...cell, sub_turn_index: 0 },
      ),
      makePlacedPacket(
        {
          type: "code_mode_delta",
          stdout: "2\n",
          status: "terminated",
          response_ended: true,
        },
        cell,
      ),
    ];
    // The closing record follows the step's section end in both. Live, it
    // also follows the streamed answer; replay sends it before the answer.
    const orders: [string, Packet[]][] = [
      ["live", [...runningObservation, messageStart(1), ...closingRecord]],
      [
        "replay",
        [
          ...runningObservation,
          ...closingRecord,
          messageStart(1),
          sectionEnd(1),
        ],
      ],
    ];

    it.each(orders)("joins its step in %s order", (_order, packets) => {
      const state = run(packets);
      expect(state.toolGroups.map(keyOf)).toEqual(["0-0"]);
      expect(state.groupedPacketsMap.get("0-0")?.at(-1)?.obj).toMatchObject({
        response_ended: true,
      });
      expect(state.finalAnswerComing).toBe(true);
    });
  });

  it("keeps unique images across separate generation steps", () => {
    const first = { file_id: "a", url: "a", revised_prompt: "first" };
    const second = { file_id: "b", url: "b", revised_prompt: "second" };
    const state = run([
      makePlacedPacket({ type: "image_generation_start" }, { turn_index: 0 }),
      makePlacedPacket(
        { type: "image_generation_final", images: [first] },
        { turn_index: 0 },
      ),
      sectionEnd(0),
      makePlacedPacket({ type: "image_generation_start" }, { turn_index: 1 }),
      makePlacedPacket(
        { type: "image_generation_final", images: [{ ...first }, second] },
        { turn_index: 1 },
      ),
      sectionEnd(1),
      messageStart(2),
    ]);
    expect(state.generatedImages).toEqual([first, second]);
  });

  it("groups incrementally across flushes (cursor advances, prior turns survive)", () => {
    let state = createInitialState(1);
    state = processPackets(state, [reasoningStart(0)]);
    expect(state.toolGroups.map(keyOf)).toEqual(["0-0"]);
    expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(false);

    state = processPackets(state, [reasoningStart(0), messageStart(1)]);
    expect(state.nextPacketIndex).toBe(2);
    expect(state.toolGroups.map(keyOf)).toEqual(["0-0"]);
    expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    expect(state.potentialDisplayGroups.map(keyOf)).toEqual(["1-0"]);
  });
});

describe("nested research packet ownership", () => {
  it.each(["section_end", "error"] as const)(
    "nested %s leaves the parent open until next turn or Stop",
    (endType) => {
      for (const closing of [messageStart(1), stopAt(0)]) {
        const nested = { turn_index: 0, sub_turn_index: 0 };
        const packets = [
          makePlacedPacket(
            { type: "research_agent_start", research_task: "Research" },
            { turn_index: 0 },
          ),
          makePlacedPacket(
            { type: "search_tool_start", is_internet_search: false },
            nested,
          ),
          makePlacedPacket({ type: endType }, nested),
          makePlacedPacket(
            {
              type: "message_start",
              id: "nested",
              content: "",
              final_documents: null,
              pre_answer_processing_seconds: 99,
            },
            { turn_index: 0, sub_turn_index: 1 },
          ),
          makePlacedPacket(
            { type: "message_delta", content: "Child answer" },
            { turn_index: 0, sub_turn_index: 1 },
          ),
        ];
        const state = run(packets);
        expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(false);
        expect(state.finalAnswerComing).toBe(false);
        expect(state.toolProcessingDuration).toBeUndefined();
        const result = processPackets(state, [...packets, closing]);
        const parentEnds = (result.groupedPacketsMap.get("0-0") ?? []).filter(
          (packet) =>
            packet.obj.type === PacketType.SECTION_END &&
            packet.placement.sub_turn_index == null,
        );
        expect(parentEnds).toHaveLength(1);
        expect(result.groupKeysWithSectionEnd.has("0-0")).toBe(true);
        expect(result.finalAnswerComing).toBe(
          closing.obj.type === PacketType.MESSAGE_START,
        );
      }
    },
  );

  it("gives a group only its own packets, so nested calls do not change or end it", () => {
    const codingStart = makePlacedPacket(
      { type: "coding_agent_start", query: "fix", repo: null },
      { turn_index: 0 },
    );
    const nested = { turn_index: 0, sub_turn_index: 0 };
    const state = run([
      codingStart,
      makePlacedPacket({ type: "bash_tool_start", cmd: "ls" }, nested),
      makePlacedPacket({ type: "error", message: "exit 1" }, nested),
    ]);
    const [group] = state.toolGroups;
    expect(group?.packets).toEqual([codingStart]);
    expect(isCodingAgentPackets(group?.packets ?? [])).toBe(true);
    expect(isToolComplete(group?.packets ?? [])).toBe(false);
  });

  it("nested messages preserve the top-level answer timing", () => {
    const state = run([
      messageStart(0, 7),
      makePlacedPacket(
        {
          type: "message_start",
          id: "nested",
          content: "",
          final_documents: null,
          pre_answer_processing_seconds: 99,
        },
        { turn_index: 0, sub_turn_index: 0 },
      ),
    ]);
    expect(state.toolProcessingDuration).toBe(7);
  });
});

it.each([undefined, null])(
  "explicit parent ends prevent duplicate closure (%s)",
  (subTurnIndex) => {
    for (const endType of ["section_end", "error"] as const) {
      const state = run([
        searchStart(0),
        makePlacedPacket(
          { type: endType },
          { turn_index: 0, sub_turn_index: subTurnIndex },
        ),
        stopAt(0),
      ]);
      const ends = (state.groupedPacketsMap.get("0-0") ?? []).filter(
        (packet) =>
          packet.obj.type === PacketType.SECTION_END ||
          packet.obj.type === PacketType.ERROR,
      );
      expect(ends).toHaveLength(1);
    }
  },
);
