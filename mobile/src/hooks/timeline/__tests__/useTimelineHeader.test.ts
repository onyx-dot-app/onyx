import { describe, expect, it } from "@jest/globals";
import { renderHook } from "@testing-library/react-native";

import { PacketType, StopReason } from "@/chat/streamingModels";
import { TurnGroup } from "@/chat/timeline/transformers";
import { useTimelineHeader } from "@/hooks/timeline/useTimelineHeader";

import { makePacket, makeStep, makeTurn } from "./testHelpers";

function headerFor(
  type: PacketType,
  extra: Record<string, unknown> = {},
): string {
  const turn: TurnGroup = makeTurn(0, [
    makeStep(0, 0, [makePacket(type, { turn_index: 0 }, extra)]),
  ]);
  return renderHook(() => useTimelineHeader([turn])).result.current.headerText;
}

describe("useTimelineHeader — text map", () => {
  it("shows Thinking... before any packets arrive", () => {
    const { result } = renderHook(() => useTimelineHeader([]));
    expect(result.current.headerText).toBe("Thinking...");
    expect(result.current.hasPackets).toBe(false);
  });

  it("shows the image header when generating with no tool packets", () => {
    const { result } = renderHook(() => useTimelineHeader([], undefined, true));
    expect(result.current.headerText).toBe("Generating image...");
  });

  it("maps each activity packet type to its label", () => {
    expect(headerFor(PacketType.REASONING_START)).toBe("Thinking");
    expect(headerFor(PacketType.FETCH_TOOL_START)).toBe("Reading");
    expect(headerFor(PacketType.PYTHON_TOOL_START)).toBe("Executing code");
    expect(headerFor(PacketType.IMAGE_GENERATION_TOOL_START)).toBe(
      "Generating images",
    );
    expect(headerFor(PacketType.FILE_READER_START)).toBe("Reading file");
    expect(headerFor(PacketType.MEMORY_TOOL_START)).toBe("Updating memory...");
    expect(headerFor(PacketType.MEMORY_TOOL_NO_ACCESS)).toBe(
      "Updating memory...",
    );
    expect(headerFor(PacketType.DEEP_RESEARCH_PLAN_START)).toBe(
      "Generating plan",
    );
    expect(headerFor(PacketType.RESEARCH_AGENT_START)).toBe("Researching");
  });

  it("degrades search to a generic label (search sub-labels land with the search phase)", () => {
    expect(headerFor(PacketType.SEARCH_TOOL_START)).toBe("Searching");
  });

  it("names the custom tool when provided, else a generic tool label", () => {
    expect(headerFor(PacketType.CUSTOM_TOOL_START, { tool_name: "Jira" })).toBe(
      "Executing Jira",
    );
    expect(headerFor(PacketType.CUSTOM_TOOL_START)).toBe("Executing tool");
  });

  it("falls back to Thinking... for an unmapped first packet", () => {
    expect(headerFor(PacketType.TOP_LEVEL_BRANCHING)).toBe("Thinking...");
  });
});

describe("useTimelineHeader — userStopped", () => {
  it("flags userStopped only on USER_CANCELLED", () => {
    const turn = makeTurn(0, [
      makeStep(0, 0, [makePacket(PacketType.REASONING_START)]),
    ]);
    expect(
      renderHook(() => useTimelineHeader([turn], StopReason.USER_CANCELLED))
        .result.current.userStopped,
    ).toBe(true);
    expect(
      renderHook(() => useTimelineHeader([turn], StopReason.FINISHED)).result
        .current.userStopped,
    ).toBe(false);
    expect(
      renderHook(() => useTimelineHeader([turn])).result.current.userStopped,
    ).toBe(false);
  });
});
