import { describe, expect, it } from "@jest/globals";

import { Packet } from "@/chat/streamingModels";

import { createInitialState, processPackets } from "@/chat/messageProcessor";

import {
  makeCitationPacket,
  makeMessageStartPacket,
  makeSearchDoc,
  makeSearchDocsPacket,
  makeStopPacket,
} from "./fixtures";

describe("messageProcessor", () => {
  it("retains reclassified commentary outside the tool timeline", () => {
    const initial: Packet = {
      identity: {
        response_id: 1,
        run_id: "root",
        message_id: "root:0",
        part_id: "answer",
      },
      obj: {
        type: "item_update",
        item: {
          kind: "text",
          purpose: "answer",
          text: "Checking sources",
          status: "running",
          documents: [],
          citations: [],
        },
      },
    };
    const state = processPackets(createInitialState(1), [initial]);
    expect(state.potentialDisplayGroups).toHaveLength(1);
    const commentary: Packet = {
      identity: initial.identity,
      obj: {
        type: "item_update",
        item: {
          kind: "text",
          purpose: "commentary",
          text: "Checking sources",
          status: "complete",
          documents: [],
          citations: [],
        },
      },
    };
    processPackets(state, [initial, commentary]);
    expect(state.potentialDisplayGroups).toHaveLength(0);
    expect(state.toolGroups).toHaveLength(0);
    expect(state.narrationGroups[0]?.items[0]?.content).toMatchObject({
      text: "Checking sources",
      purpose: "commentary",
    });
    const saved = processPackets(createInitialState(1), [commentary]);
    expect(saved.narrationGroups).toEqual(state.narrationGroups);
  });

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

  it("collects documents from tool metadata and response text", () => {
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

  it("marks complete on stop", () => {
    let state = createInitialState(1);
    expect(state.isComplete).toBe(false);
    state = processPackets(state, [makeStopPacket()]);
    expect(state.isComplete).toBe(true);
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
});
