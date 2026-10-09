import { describe, expect, it } from "@jest/globals";
import { renderHook } from "@testing-library/react-native";

import { PacketType } from "@/chat/streamingModels";
import { TurnGroup } from "@/chat/timeline/transformers";
import { useTimelineMetrics } from "@/hooks/timeline/useTimelineMetrics";

import { makePacket, makeStep, makeTurn } from "./testHelpers";

function run(turnGroups: TurnGroup[], userStopped = false) {
  return renderHook(() => useTimelineMetrics(turnGroups, userStopped)).result
    .current;
}

const reasoning = makeStep(0, 0, [makePacket(PacketType.REASONING_START)]);
const researchAgent = makeStep(1, 0, [
  makePacket(PacketType.RESEARCH_AGENT_START, { turn_index: 1 }),
]);
const codingAgent = makeStep(1, 0, [
  makePacket(PacketType.CODING_AGENT_START, { turn_index: 1 }),
]);

describe("useTimelineMetrics", () => {
  it("returns zeros for an empty timeline", () => {
    const m = run([]);
    expect(m.totalSteps).toBe(0);
    expect(m.isSingleStep).toBe(false);
    expect(m.lastTurnGroup).toBeUndefined();
    expect(m.lastStep).toBeUndefined();
    expect(m.lastStepIsResearchAgent).toBe(false);
    expect(m.lastStepIsCodingAgent).toBe(false);
    expect(m.lastStepSupportsCollapsedStreaming).toBe(false);
  });

  it("counts a single reasoning step as a single step", () => {
    const m = run([makeTurn(0, [reasoning])]);
    expect(m.totalSteps).toBe(1);
    expect(m.isSingleStep).toBe(true);
    expect(m.lastStep).toBe(reasoning);
    expect(m.lastStepSupportsCollapsedStreaming).toBe(true);
    expect(m.lastStepIsResearchAgent).toBe(false);
    expect(m.lastStepIsCodingAgent).toBe(false);
  });

  it("isSingleStep is false when the user stopped", () => {
    expect(run([makeTurn(0, [reasoning])], true).isSingleStep).toBe(false);
  });

  it("sums steps across turns and analyzes the last step", () => {
    const m = run([makeTurn(0, [reasoning]), makeTurn(1, [researchAgent])]);
    expect(m.totalSteps).toBe(2);
    expect(m.isSingleStep).toBe(false);
    expect(m.lastTurnGroup?.turnIndex).toBe(1);
    expect(m.lastStep).toBe(researchAgent);
    expect(m.lastStepIsResearchAgent).toBe(true);
    expect(m.lastStepIsCodingAgent).toBe(false);
  });

  it("flags a coding-agent last step", () => {
    const m = run([makeTurn(0, [reasoning]), makeTurn(1, [codingAgent])]);
    expect(m.lastStepIsCodingAgent).toBe(true);
    expect(m.lastStepIsResearchAgent).toBe(false);
  });

  it("counts every step of a parallel turn", () => {
    const parallel = makeTurn(0, [
      makeStep(0, 0, [makePacket(PacketType.SEARCH_TOOL_START)]),
      makeStep(0, 1, [makePacket(PacketType.PYTHON_TOOL_START)]),
    ]);
    expect(run([parallel]).totalSteps).toBe(2);
  });
});
