import { describe, expect, it } from "@jest/globals";

import { createInitialState, processPackets } from "@/chat/messageProcessor";

import {
  makeCitationPacket,
  makeMessageStartPacket,
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
