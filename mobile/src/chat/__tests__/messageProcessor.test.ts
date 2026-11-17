import { describe, expect, it } from "@jest/globals";

import { createInitialState, processPackets } from "@/chat/messageProcessor";
import { Packet, PacketType, StopReason } from "@/chat/streamingModels";

import {
  makeCitationPacket,
  makeMessageStartPacket,
  makePacket,
  makeSearchDoc,
  makeSearchDocsPacket,
  makeStopPacket,
} from "./fixtures";

describe("messageProcessor", () => {
  it("builds citationMap and deduped citations in first-cite order", () => {
    let state = createInitialState(1);
    state = processPackets(state, [
      makeCitationPacket(1, "d1"),
      makeCitationPacket(2, "d2"),
      makeCitationPacket(1, "d1"), // repeat — deduped
    ]);
    expect(state.citationMap).toEqual({ 1: "d1", 2: "d2" });
    expect(state.citations).toEqual([
      { citation_num: 1, document_id: "d1" },
      { citation_num: 2, document_id: "d2" },
    ]);
  });

  it("upserts documentMap from both document packet types and final_documents", () => {
    let state = createInitialState(1);
    state = processPackets(state, [
      makeSearchDocsPacket([makeSearchDoc({ document_id: "d1" })], "search"),
      makeSearchDocsPacket([makeSearchDoc({ document_id: "d2" })], "open_url"),
      makeMessageStartPacket([makeSearchDoc({ document_id: "d3" })]),
    ]);
    expect(Array.from(state.documentMap.keys()).sort()).toEqual([
      "d1",
      "d2",
      "d3",
    ]);
  });

  it("rebuilds when a replay replaces the packets at the same length", () => {
    let state = processPackets(createInitialState(1), [
      makeMessageStartPacket([]),
      makeStopPacket(),
    ]);
    expect(state.stopPacketSeen).toBe(true);

    state = processPackets(state, [
      makeMessageStartPacket([]),
      makePacket({ type: PacketType.MESSAGE_DELTA, content: "more" }),
    ]);

    expect(state.stopPacketSeen).toBe(false);
    expect(state.isComplete).toBe(false);
  });

  it("marks complete on stop", () => {
    let state = createInitialState(1);
    expect(state.isComplete).toBe(false);
    state = processPackets(state, [makeStopPacket()]);
    expect(state.isComplete).toBe(true);
  });

  it("does not complete a response that waits for approval", () => {
    const state = processPackets(createInitialState(1), [
      {
        placement: { turn_index: 0 },
        obj: {
          type: PacketType.STOP,
          stop_reason: StopReason.AWAITING_USER,
        },
      },
    ]);
    expect(state.isComplete).toBe(false);
    expect(state.stopPacketSeen).toBe(false);
  });

  it("keeps a question call out of the steps and the response open while it waits", () => {
    const question: Packet = {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.TOOL_QUESTION_REQUEST,
        question_request_id: "q1",
        tool_call_id: "c1",
        questions: [
          {
            id: "scope",
            header: "Scope",
            question: "Which scope?",
            options: [
              { label: "Small", description: "One file." },
              { label: "Large", description: "The whole app." },
            ],
          },
        ],
      },
    };
    const waiting = processPackets(createInitialState(1), [
      question,
      {
        placement: { turn_index: 0 },
        obj: { type: PacketType.STOP, stop_reason: StopReason.AWAITING_USER },
      },
    ]);
    expect(waiting.toolGroups).toEqual([]);
    expect(waiting.potentialDisplayGroups).toEqual([]);
    expect(waiting.stopPacketSeen).toBe(false);

    // The continuation replays the question, resolves it, and answers.
    const answered = processPackets(createInitialState(1), [
      question,
      {
        placement: { turn_index: 0 },
        obj: {
          type: PacketType.TOOL_QUESTION_RESOLVED,
          question_request_id: "q1",
          outcome: "answered",
          answered_via: "message",
          message: "Small",
        },
      },
      makePacket({ type: PacketType.SECTION_END }, 0),
      makePacket({ type: PacketType.MESSAGE_START, id: "m", content: "" }, 1),
      makePacket({ type: PacketType.STOP }, 1),
    ]);
    expect(answered.toolGroups).toEqual([]);
    expect(
      answered.potentialDisplayGroups.map((group) => group.turn_index),
    ).toEqual([1]);
    expect(answered.isComplete).toBe(true);
    expect(answered.finalAnswerComing).toBe(true);
  });

  it("shows text whose step also called a tool once the response stops", () => {
    let state = createInitialState(1);
    state = processPackets(state, [
      makeMessageStartPacket(),
      makePacket({ type: "custom_tool_start", tool_name: "wait_agents" }, 1),
    ]);
    expect(state.finalAnswerComing).toBe(false);
    state = processPackets(state, [
      makeMessageStartPacket(),
      makePacket({ type: "custom_tool_start", tool_name: "wait_agents" }, 1),
      makeStopPacket(),
    ]);
    expect(state.finalAnswerComing).toBe(true);
    expect(state.potentialDisplayGroups).toHaveLength(1);
  });

  it("processes only new packets across flushes (no double count)", () => {
    let state = createInitialState(1);
    const packets = [makeCitationPacket(1, "d1")];
    state = processPackets(state, packets);
    state = processPackets(state, packets); // same array, no growth
    expect(state.citations).toHaveLength(1);
    expect(state.nextPacketIndex).toBe(1);
  });

  it("resets when the packet array shrinks (regenerate / reload)", () => {
    let state = createInitialState(1);
    state = processPackets(state, [
      makeCitationPacket(1, "d1"),
      makeCitationPacket(2, "d2"),
    ]);
    expect(state.citations).toHaveLength(2);

    state = processPackets(state, [makeCitationPacket(3, "d3")]); // shorter array
    expect(state.citations).toEqual([{ citation_num: 3, document_id: "d3" }]);
    expect(state.citationMap).toEqual({ 3: "d3" });
  });

  it("keeps approval packets in their tool's step without changing it", () => {
    const start: Packet = {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.CUSTOM_TOOL_START,
        tool_name: "lookup",
        display_name: "Lookup",
      },
    } as Packet;
    const request: Packet = {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.TOOL_APPROVAL_REQUEST,
        approval_id: "a1",
        tool_call_id: "c1",
        tool_name: "lookup",
        display_name: "Lookup",
        arguments: {},
      },
    };
    const resolved: Packet = {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.TOOL_APPROVAL_RESOLVED,
        approval_id: "a1",
        outcome: "approved",
      },
    };
    const state = processPackets(createInitialState(1), [
      start,
      request,
      resolved,
    ]);
    expect(state.toolGroups).toHaveLength(1);
    expect(state.toolGroups[0]?.packets).toEqual([start, request, resolved]);
    expect(state.potentialDisplayGroups).toEqual([]);
    expect(state.groupKeysWithSectionEnd.size).toBe(0);
  });

  it("does not make a step of approval packets alone", () => {
    const state = processPackets(createInitialState(1), [
      {
        placement: { turn_index: 1 },
        obj: {
          type: PacketType.TOOL_APPROVAL_RESOLVED,
          approval_id: "a1",
          outcome: "cancelled",
        },
      },
    ]);
    expect(state.toolGroups).toEqual([]);
    expect(state.potentialDisplayGroups).toEqual([]);
  });
});
