import { describe, expect, it } from "@jest/globals";

import {
  createInitialState,
  processPackets,
  type GroupedPacket,
  type ProcessedMessageState,
} from "@/chat/messageProcessor";
import { PacketType, type Packet } from "@/chat/streamingModels";

import { makePlacedPacket } from "../../__tests__/fixtures";

// Convenience builders for the packet families this PR groups.
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
    // The new turn 1 closes turn 0's group.
    expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(true);
    expect(hasSectionEnd(state, "0-0")).toBe(true);
    // Turn 1 is still open (no newer turn, no stop).
    expect(state.groupKeysWithSectionEnd.has("1-0")).toBe(false);
  });

  it("does NOT close a sibling when only tab_index changes within a turn", () => {
    const state = run([searchStart(0, 0), searchStart(0, 1)]);
    expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(false);
    expect(state.groupKeysWithSectionEnd.has("0-1")).toBe(false);
    // Both are parallel tabs of the same turn.
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
    // message_start@turn0 then stop@turn0: there's no later turn, so the turn-transition path
    // never fires — ONLY handleStopPacket's injection loop closes the final-answer group.
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
    expect(ends).toHaveLength(1); // the real one, not synthesized twice
  });

  it("keeps TOP_LEVEL_BRANCHING as metadata (not in any group)", () => {
    const state = run([
      makePlacedPacket(
        { type: "top_level_branching", num_parallel_branches: 2 },
        { turn_index: 0 },
      ),
      searchStart(0, 0),
      searchStart(0, 1),
    ]);
    expect(state.expectedBranches.get(0)).toBe(2);
    expect(state.groupedPacketsMap.has("0-0")).toBe(true);
    // Only the two search groups have content; the branching packet is not grouped.
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

  it("does NOT reset finalAnswerComing for reasoning after the message", () => {
    const state = run([messageStart(0), reasoningStart(1)]);
    expect(state.finalAnswerComing).toBe(true);
  });

  it("filters out a categorized tool group that has no content packet", () => {
    // "0-0" is a real tool group (queries_delta is a tool packet, so it enters toolGroupKeys) but
    // has no *_START/content packet, so hasContentPackets drops it — while the sibling with a real
    // SEARCH_TOOL_START is kept. This exercises the content filter, not key categorization.
    const state = run([searchQueriesDelta(0), searchStart(1)]);
    expect(state.toolGroupKeys.has("0-0")).toBe(true); // categorized as a tool group…
    expect(state.toolGroups.map(keyOf)).toEqual(["1-0"]); // …but filtered out for lack of content
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

  it("counts generated images and flags image generation", () => {
    const state = run([
      makePlacedPacket({ type: "image_generation_start" }, { turn_index: 0 }),
      makePlacedPacket(
        {
          type: "image_generation_final",
          images: [
            { file_id: "a", url: "u", revised_prompt: "p" },
            { file_id: "b", url: "u", revised_prompt: "p" },
          ],
        },
        { turn_index: 0 },
      ),
    ]);
    expect(state.isGeneratingImage).toBe(true);
    expect(state.generatedImageCount).toBe(2);
  });

  it("groups incrementally across flushes (cursor advances, prior turns survive)", () => {
    let state = createInitialState(1);
    state = processPackets(state, [reasoningStart(0)]);
    expect(state.toolGroups.map(keyOf)).toEqual(["0-0"]);
    expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(false); // still open

    // Flush 2: same prior packet + a new turn's message_start (growing array).
    state = processPackets(state, [reasoningStart(0), messageStart(1)]);
    expect(state.nextPacketIndex).toBe(2); // cursor advanced; turn-0 packet not re-processed
    expect(state.toolGroups.map(keyOf)).toEqual(["0-0"]); // turn-0 group survived
    expect(state.groupKeysWithSectionEnd.has("0-0")).toBe(true); // closed by the turn-1 transition
    expect(state.potentialDisplayGroups.map(keyOf)).toEqual(["1-0"]); // new display group merged in
  });
});
