import { describe, expect, it } from "@jest/globals";
import { renderHook } from "@testing-library/react-native";

import { PacketType } from "@/chat/streamingModels";
import { TurnGroup } from "@/chat/timeline/transformers";
import { useTimelineStepState } from "@/hooks/timeline/useTimelineStepState";

import { makePacket, makeStep, makeTurn } from "./testHelpers";

function run(turnGroups: TurnGroup[]) {
  return renderHook(() => useTimelineStepState(turnGroups)).result.current;
}

const memoryStep = makeStep(0, 0, [makePacket(PacketType.MEMORY_TOOL_START)]);
const reasoningStep = makeStep(0, 0, [makePacket(PacketType.REASONING_START)]);

describe("useTimelineStepState (dormant in 9b)", () => {
  it("leaves memory content null until the memory renderer phase", () => {
    const s = run([makeTurn(0, [memoryStep])]);
    expect(s.memoryText).toBeNull();
    expect(s.memoryOperation).toBeNull();
    expect(s.memoryId).toBeNull();
    expect(s.memoryIndex).toBeNull();
  });

  it("isMemoryOnly true when every step is a memory step", () => {
    expect(run([makeTurn(0, [memoryStep])]).isMemoryOnly).toBe(true);
    expect(
      run([
        makeTurn(0, [memoryStep]),
        makeTurn(1, [
          makeStep(1, 0, [
            makePacket(PacketType.MEMORY_TOOL_NO_ACCESS, { turn_index: 1 }),
          ]),
        ]),
      ]).isMemoryOnly,
    ).toBe(true);
  });

  it("isMemoryOnly false when any step is non-memory", () => {
    expect(
      run([makeTurn(0, [memoryStep]), makeTurn(1, [reasoningStep])])
        .isMemoryOnly,
    ).toBe(false);
  });

  it("isMemoryOnly false for an empty timeline", () => {
    expect(run([]).isMemoryOnly).toBe(false);
  });
});
