import { describe, expect, it } from "@jest/globals";
import { renderHook } from "@testing-library/react-native";

import { PacketType } from "@/chat/streamingModels";
import {
  TimelineUIState,
  TimelineUIStateInput,
  useTimelineUIState,
} from "@/hooks/timeline/useTimelineUIState";

import { makePacket, makeStep, makeTurn } from "./testHelpers";

const sequentialTurn = makeTurn(0, [
  makeStep(0, 0, [makePacket(PacketType.REASONING_START)]),
]);
const parallelTurn = makeTurn(0, [
  makeStep(0, 0, [makePacket(PacketType.SEARCH_TOOL_START)]),
  makeStep(0, 1, [makePacket(PacketType.PYTHON_TOOL_START)]),
]);

function baseInput(
  overrides: Partial<TimelineUIStateInput> = {},
): TimelineUIStateInput {
  return {
    stopPacketSeen: false,
    hasPackets: false,
    hasDisplayContent: false,
    userStopped: false,
    isExpanded: false,
    lastTurnGroup: undefined,
    lastStep: undefined,
    lastStepSupportsCollapsedStreaming: false,
    lastStepHasCollapsedContent: false,
    lastStepIsResearchAgent: false,
    parallelActiveStepSupportsCollapsedStreaming: false,
    parallelActiveStepHasCollapsedContent: false,
    isGeneratingImage: false,
    finalAnswerComing: false,
    ...overrides,
  };
}

function run(overrides: Partial<TimelineUIStateInput> = {}) {
  return renderHook(() => useTimelineUIState(baseInput(overrides))).result
    .current;
}

describe("useTimelineUIState — the 7 states", () => {
  it("EMPTY when nothing has arrived", () => {
    expect(run().uiState).toBe(TimelineUIState.EMPTY);
  });

  it("DISPLAY_CONTENT_ONLY when only the final message streamed (no tools)", () => {
    expect(run({ hasDisplayContent: true }).uiState).toBe(
      TimelineUIState.DISPLAY_CONTENT_ONLY,
    );
  });

  it("STREAMING_SEQUENTIAL for an active single-step turn", () => {
    expect(
      run({ hasPackets: true, lastTurnGroup: sequentialTurn }).uiState,
    ).toBe(TimelineUIState.STREAMING_SEQUENTIAL);
  });

  it("STREAMING_PARALLEL for an active parallel turn", () => {
    expect(run({ hasPackets: true, lastTurnGroup: parallelTurn }).uiState).toBe(
      TimelineUIState.STREAMING_PARALLEL,
    );
  });

  it("STOPPED when the user cancelled without display content", () => {
    expect(
      run({ stopPacketSeen: true, hasPackets: true, userStopped: true })
        .uiState,
    ).toBe(TimelineUIState.STOPPED);
  });

  it("COMPLETED_EXPANDED when done and expanded", () => {
    expect(
      run({ stopPacketSeen: true, hasPackets: true, isExpanded: true }).uiState,
    ).toBe(TimelineUIState.COMPLETED_EXPANDED);
  });

  it("COMPLETED_COLLAPSED when done and collapsed", () => {
    expect(run({ stopPacketSeen: true, hasPackets: true }).uiState).toBe(
      TimelineUIState.COMPLETED_COLLAPSED,
    );
  });

  it("stays streaming while generating an image even with display content", () => {
    // isGeneratingImage keeps it in the streaming branch instead of DISPLAY_CONTENT_ONLY.
    expect(
      run({
        hasPackets: true,
        hasDisplayContent: true,
        isGeneratingImage: true,
        lastTurnGroup: sequentialTurn,
      }).uiState,
    ).toBe(TimelineUIState.STREAMING_SEQUENTIAL);
  });
});

describe("useTimelineUIState — convenience booleans", () => {
  it("isStreaming true only for streaming states", () => {
    expect(
      run({ hasPackets: true, lastTurnGroup: sequentialTurn }).isStreaming,
    ).toBe(true);
    expect(run({ stopPacketSeen: true, hasPackets: true }).isStreaming).toBe(
      false,
    );
  });

  it("isCompleted true for both completed states and stopped", () => {
    expect(run({ stopPacketSeen: true, hasPackets: true }).isCompleted).toBe(
      true,
    );
    expect(
      run({ stopPacketSeen: true, hasPackets: true, isExpanded: true })
        .isCompleted,
    ).toBe(true);
    expect(
      run({ stopPacketSeen: true, hasPackets: true, userStopped: true })
        .isCompleted,
    ).toBe(true);
    expect(run().isCompleted).toBe(false);
  });

  it("isActivelyExecuting tracks tool execution", () => {
    expect(
      run({ hasPackets: true, lastTurnGroup: sequentialTurn })
        .isActivelyExecuting,
    ).toBe(true);
    expect(
      run({ stopPacketSeen: true, hasPackets: true }).isActivelyExecuting,
    ).toBe(false);
  });
});

describe("useTimelineUIState — display + styling flags", () => {
  it("showParallelTabs only while collapsed-streaming a parallel turn", () => {
    expect(
      run({ hasPackets: true, lastTurnGroup: parallelTurn }).showParallelTabs,
    ).toBe(true);
    expect(
      run({ hasPackets: true, lastTurnGroup: parallelTurn, isExpanded: true })
        .showParallelTabs,
    ).toBe(false);
    expect(
      run({ hasPackets: true, lastTurnGroup: sequentialTurn }).showParallelTabs,
    ).toBe(false);
  });

  it("showCollapsedCompact requires a supporting last step with content", () => {
    const on = run({
      hasPackets: true,
      lastTurnGroup: sequentialTurn,
      lastStep: sequentialTurn.steps[0],
      lastStepSupportsCollapsedStreaming: true,
      lastStepHasCollapsedContent: true,
    });
    expect(on.showCollapsedCompact).toBe(true);
    const off = run({
      hasPackets: true,
      lastTurnGroup: sequentialTurn,
      lastStep: sequentialTurn.steps[0],
      lastStepSupportsCollapsedStreaming: true,
      lastStepHasCollapsedContent: false,
    });
    expect(off.showCollapsedCompact).toBe(false);
  });

  it("showCollapsedParallel requires parallel tabs + active parallel content", () => {
    expect(
      run({
        hasPackets: true,
        lastTurnGroup: parallelTurn,
        parallelActiveStepSupportsCollapsedStreaming: true,
        parallelActiveStepHasCollapsedContent: true,
      }).showCollapsedParallel,
    ).toBe(true);
  });

  it("showDoneStep on final-answer-coming while expanded", () => {
    expect(
      run({ finalAnswerComing: true, hasPackets: true, isExpanded: true })
        .showDoneStep,
    ).toBe(true);
    // Collapsed → no done step even when finalAnswerComing.
    expect(
      run({ finalAnswerComing: true, hasPackets: true }).showDoneStep,
    ).toBe(false);
  });

  it("showStoppedStep only when user-stopped, expanded, no display content", () => {
    expect(
      run({
        stopPacketSeen: true,
        hasPackets: true,
        userStopped: true,
        isExpanded: true,
      }).showStoppedStep,
    ).toBe(true);
    expect(
      run({
        stopPacketSeen: true,
        hasPackets: true,
        userStopped: true,
        isExpanded: true,
        hasDisplayContent: true,
      }).showStoppedStep,
    ).toBe(false);
  });

  it("hasDoneIndicator excludes research-agent last steps", () => {
    expect(
      run({ stopPacketSeen: true, hasPackets: true, isExpanded: true })
        .hasDoneIndicator,
    ).toBe(true);
    expect(
      run({
        stopPacketSeen: true,
        hasPackets: true,
        isExpanded: true,
        lastStepIsResearchAgent: true,
      }).hasDoneIndicator,
    ).toBe(false);
  });

  it("showTintedBackground while executing or expanded; showRoundedBottom otherwise", () => {
    const streaming = run({ hasPackets: true, lastTurnGroup: sequentialTurn });
    expect(streaming.showTintedBackground).toBe(true);
    expect(streaming.showRoundedBottom).toBe(true);

    const collapsedCompact = run({
      hasPackets: true,
      lastTurnGroup: sequentialTurn,
      lastStep: sequentialTurn.steps[0],
      lastStepSupportsCollapsedStreaming: true,
      lastStepHasCollapsedContent: true,
    });
    expect(collapsedCompact.showRoundedBottom).toBe(false);

    const completedCollapsed = run({ stopPacketSeen: true, hasPackets: true });
    expect(completedCollapsed.showTintedBackground).toBe(false);
    expect(completedCollapsed.showRoundedBottom).toBe(true);
  });
});
