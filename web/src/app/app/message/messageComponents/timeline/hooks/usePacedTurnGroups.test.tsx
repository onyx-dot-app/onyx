/**
 * Tests for usePacedTurnGroups hook
 *
 * Tests the pacing logic that reveals steps with delays during streaming.
 * Uses @testing-library/react's renderHook with fake timers.
 */
import { renderHook, act } from "@testing-library/react";
import {
  TurnGroup,
  TransformedStep,
} from "@/app/app/message/messageComponents/timeline/transformers";
import { GroupedItem } from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";
import { usePacedTurnGroups } from "@/app/app/message/messageComponents/timeline/hooks/usePacedTurnGroups";
import {
  toolItem,
  answerItem,
} from "@/app/app/message/messageComponents/timeline/hooks/__tests__/testHelpers";

function createStep(
  turnIndex: number,
  tabIndex: number,
  name = "internal_search"
): TransformedStep {
  return {
    key: `${turnIndex}-${tabIndex}`,
    turnIndex,
    tabIndex,
    items: [toolItem(turnIndex, tabIndex, name)],
  };
}
function createTurnGroup(steps: TransformedStep[]): TurnGroup {
  const first = steps[0];
  if (!first) throw new Error("TurnGroup needs at least one step");
  return { turnIndex: first.turnIndex, steps, isParallel: steps.length > 1 };
}
function createDisplayGroup(turnIndex: number): GroupedItem {
  return {
    turn_index: turnIndex,
    tab_index: 0,
    items: [answerItem(turnIndex)],
  };
}

// ============================================================================
// Tests
// ============================================================================

describe("usePacedTurnGroups", () => {
  it("shows resumed tool steps immediately while the response is still running", () => {
    const groups = [
      createTurnGroup([createStep(0, 0)]),
      createTurnGroup([createStep(1, 0, "open_url")]),
    ];
    const { result, rerender } = renderHook(
      ({ groups }) => usePacedTurnGroups(groups, [], false, 1, false, true),
      { initialProps: { groups } }
    );
    expect(result.current.pacedTurnGroups).toEqual(groups);

    const updatedGroups = [
      ...groups,
      createTurnGroup([createStep(2, 0, "web_search")]),
    ];
    rerender({ groups: updatedGroups });
    expect(result.current.pacedTurnGroups).toEqual(updatedGroups);
  });

  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe("initial state", () => {
    test("returns empty arrays when no turn groups provided", () => {
      const { result } = renderHook(() =>
        usePacedTurnGroups([], [], false, 1, false)
      );

      expect(result.current.pacedTurnGroups).toEqual([]);
      expect(result.current.pacedDisplayGroups).toEqual([]);
      expect(result.current.pacedFinalAnswerComing).toBe(false);
    });
  });

  describe("bypass pacing for completed messages", () => {
    test("returns all turn groups immediately when stopPacketSeen on first render", () => {
      const step1 = createStep(0, 0);
      const step2 = createStep(1, 0);
      const turnGroups = [createTurnGroup([step1]), createTurnGroup([step2])];
      const displayGroups = [createDisplayGroup(2)];

      const { result } = renderHook(() =>
        usePacedTurnGroups(turnGroups, displayGroups, true, 1, true)
      );

      // All steps revealed immediately - no pacing
      expect(result.current.pacedTurnGroups.length).toBe(2);
      expect(result.current.pacedDisplayGroups.length).toBe(1);
      expect(result.current.pacedFinalAnswerComing).toBe(true);
    });
  });

  describe("stop packet handling", () => {
    test("flushes all pending steps when stop packet received", () => {
      const step1 = createStep(0, 0);
      const step2 = createStep(1, 0);
      const step3 = createStep(2, 0);

      // Start with first step
      const { result, rerender } = renderHook(
        ({ turnGroups, stopPacketSeen }) =>
          usePacedTurnGroups(turnGroups, [], stopPacketSeen, 1, false),
        {
          initialProps: {
            turnGroups: [createTurnGroup([step1])],
            stopPacketSeen: false,
          },
        }
      );

      // First step revealed immediately
      expect(result.current.pacedTurnGroups.length).toBe(1);

      // Add more steps
      rerender({
        turnGroups: [
          createTurnGroup([step1]),
          createTurnGroup([step2]),
          createTurnGroup([step3]),
        ],
        stopPacketSeen: false,
      });

      // Still only first step (others pending)
      expect(result.current.pacedTurnGroups.length).toBe(1);

      // STOP packet arrives - flush all
      rerender({
        turnGroups: [
          createTurnGroup([step1]),
          createTurnGroup([step2]),
          createTurnGroup([step3]),
        ],
        stopPacketSeen: true,
      });

      // All steps revealed immediately
      expect(result.current.pacedTurnGroups.length).toBe(3);
    });
  });

  describe("nodeId change reset", () => {
    test("resets pacing state when nodeId changes", () => {
      const step1 = createStep(0, 0);
      const turnGroups = [createTurnGroup([step1])];

      const { result, rerender } = renderHook(
        ({ nodeId }) =>
          usePacedTurnGroups(turnGroups, [], false, nodeId, false),
        { initialProps: { nodeId: 1 } }
      );

      expect(result.current.pacedTurnGroups.length).toBe(1);

      // Change nodeId - should reset state
      rerender({ nodeId: 2 });

      // First step of new message revealed immediately
      expect(result.current.pacedTurnGroups.length).toBe(1);
    });
  });

  describe("step pacing", () => {
    test("first step is revealed immediately", () => {
      const step1 = createStep(0, 0);
      const turnGroups = [createTurnGroup([step1])];

      const { result } = renderHook(() =>
        usePacedTurnGroups(turnGroups, [], false, 1, false)
      );

      // First step revealed immediately without timer
      expect(result.current.pacedTurnGroups.length).toBe(1);
      expect(result.current.pacedTurnGroups[0]?.steps[0]?.key).toBe("0-0");
    });

    test("second step is revealed after 200ms delay", () => {
      const step1 = createStep(0, 0);

      const { result, rerender } = renderHook(
        ({ turnGroups }) => usePacedTurnGroups(turnGroups, [], false, 1, false),
        { initialProps: { turnGroups: [createTurnGroup([step1])] } }
      );

      // First step revealed
      expect(result.current.pacedTurnGroups.length).toBe(1);

      // Add second step
      const step2 = createStep(1, 0);
      rerender({
        turnGroups: [createTurnGroup([step1]), createTurnGroup([step2])],
      });

      // Still only first step
      expect(result.current.pacedTurnGroups.length).toBe(1);

      // Advance timer
      act(() => {
        jest.advanceTimersByTime(200);
      });

      // Now second step revealed
      expect(result.current.pacedTurnGroups.length).toBe(2);
    });

    test("third step is revealed after 400ms total (200ms after second)", () => {
      const step1 = createStep(0, 0);

      const { result, rerender } = renderHook(
        ({ turnGroups }) => usePacedTurnGroups(turnGroups, [], false, 1, false),
        { initialProps: { turnGroups: [createTurnGroup([step1])] } }
      );

      // First step revealed
      expect(result.current.pacedTurnGroups.length).toBe(1);

      // Add second and third steps
      const step2 = createStep(1, 0);
      const step3 = createStep(2, 0);
      rerender({
        turnGroups: [
          createTurnGroup([step1]),
          createTurnGroup([step2]),
          createTurnGroup([step3]),
        ],
      });

      // Still only first step
      expect(result.current.pacedTurnGroups.length).toBe(1);

      // After 200ms - second step
      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(2);

      // After another 200ms (400ms total) - third step
      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(3);
    });

    test("same-type steps are paced with delay (NOT batched)", () => {
      const step1 = createStep(0, 0, "internal_search");

      const { result, rerender } = renderHook(
        ({ turnGroups }) => usePacedTurnGroups(turnGroups, [], false, 1, false),
        { initialProps: { turnGroups: [createTurnGroup([step1])] } }
      );

      // First step revealed immediately
      expect(result.current.pacedTurnGroups.length).toBe(1);

      // Add two more SEARCH_TOOL steps (same type as first)
      const step2 = createStep(1, 0, "internal_search");
      const step3 = createStep(2, 0, "internal_search");
      rerender({
        turnGroups: [
          createTurnGroup([step1]),
          createTurnGroup([step2]),
          createTurnGroup([step3]),
        ],
      });

      // Still only first step - same-type steps should NOT be batched
      expect(result.current.pacedTurnGroups.length).toBe(1);

      // After 200ms - second step (even though same type)
      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(2);

      // After another 200ms - third step (even though same type)
      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(3);
    });

    test("different-type steps are paced with delay", () => {
      const step1 = createStep(0, 0, "internal_search");

      const { result, rerender } = renderHook(
        ({ turnGroups }) => usePacedTurnGroups(turnGroups, [], false, 1, false),
        { initialProps: { turnGroups: [createTurnGroup([step1])] } }
      );

      // First step revealed immediately
      expect(result.current.pacedTurnGroups.length).toBe(1);

      // Add step of different type
      const step2 = createStep(1, 0, "run_python");
      rerender({
        turnGroups: [createTurnGroup([step1]), createTurnGroup([step2])],
      });

      // Still only first step
      expect(result.current.pacedTurnGroups.length).toBe(1);

      // After 200ms - second step
      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(2);
    });
  });

  describe("display groups", () => {
    test("display groups shown only after tool pacing complete", () => {
      const step1 = createStep(0, 0);
      const displayGroup = createDisplayGroup(1);

      const { result, rerender } = renderHook(
        ({ turnGroups }) =>
          usePacedTurnGroups(turnGroups, [displayGroup], false, 1, true),
        { initialProps: { turnGroups: [createTurnGroup([step1])] } }
      );

      // First step revealed, but display groups hidden until pacing complete
      expect(result.current.pacedTurnGroups.length).toBe(1);

      // Add second step
      const step2 = createStep(1, 0);
      rerender({
        turnGroups: [createTurnGroup([step1]), createTurnGroup([step2])],
      });

      // Display groups still hidden (pacing not complete)
      expect(result.current.pacedDisplayGroups.length).toBe(0);

      // Complete pacing
      act(() => {
        jest.advanceTimersByTime(200);
      });

      // Now pacing is complete, display groups shown
      expect(result.current.pacedTurnGroups.length).toBe(2);
      expect(result.current.pacedDisplayGroups.length).toBe(1);
    });

    test("display groups shown immediately when no tool steps", () => {
      const displayGroup = createDisplayGroup(0);

      const { result } = renderHook(() =>
        usePacedTurnGroups([], [displayGroup], false, 1, true)
      );

      // No tools = pacing complete immediately
      expect(result.current.pacedDisplayGroups.length).toBe(1);
      expect(result.current.pacedFinalAnswerComing).toBe(true);
    });
  });

  describe("pacedFinalAnswerComing", () => {
    test("returns false when tool pacing not complete", () => {
      const step1 = createStep(0, 0);

      const { result, rerender } = renderHook(
        ({ turnGroups }) => usePacedTurnGroups(turnGroups, [], false, 1, true),
        { initialProps: { turnGroups: [createTurnGroup([step1])] } }
      );

      // Add second step (creates pending)
      const step2 = createStep(1, 0);
      rerender({
        turnGroups: [createTurnGroup([step1]), createTurnGroup([step2])],
      });

      // Pacing not complete
      expect(result.current.pacedFinalAnswerComing).toBe(false);

      // Complete pacing
      act(() => {
        jest.advanceTimersByTime(200);
      });

      // Now pacing complete
      expect(result.current.pacedFinalAnswerComing).toBe(true);
    });

    test("returns true when bypassing pacing", () => {
      const step1 = createStep(0, 0);
      const turnGroups = [createTurnGroup([step1])];

      const { result } = renderHook(() =>
        usePacedTurnGroups(turnGroups, [], true, 1, true)
      );

      // Bypassing pacing, so finalAnswerComing passed through
      expect(result.current.pacedFinalAnswerComing).toBe(true);
    });
  });

  describe("tool-after-message transition", () => {
    test("resets toolPacingComplete when finalAnswerComing goes true → false with new tool step", () => {
      const displayGroup = createDisplayGroup(0);

      // Step 1: Render with finalAnswerComing=true, no tool steps
      // No tools = pacing complete immediately → display groups shown
      const { result, rerender } = renderHook(
        ({ turnGroups, finalAnswerComing }) =>
          usePacedTurnGroups(
            turnGroups,
            [displayGroup],
            false,
            1,
            finalAnswerComing
          ),
        {
          initialProps: {
            turnGroups: [] as TurnGroup[],
            finalAnswerComing: true,
          },
        }
      );

      expect(result.current.pacedDisplayGroups.length).toBe(1);
      expect(result.current.pacedFinalAnswerComing).toBe(true);

      // Step 2: finalAnswerComing goes false + new tool step arrives
      // This simulates the agent switching from message streaming back to tools
      const step1 = createStep(0, 0);
      rerender({
        turnGroups: [createTurnGroup([step1])],
        finalAnswerComing: false,
      });

      // toolPacingComplete was reset, so display groups should be hidden
      // (first tool step is revealed immediately, but pacing just re-started)
      expect(result.current.pacedTurnGroups.length).toBe(1);
      expect(result.current.pacedDisplayGroups.length).toBe(0);

      // Step 3: Add a second tool step so pacing is not yet complete
      const step2 = createStep(1, 0);
      rerender({
        turnGroups: [createTurnGroup([step1]), createTurnGroup([step2])],
        finalAnswerComing: false,
      });

      // Display groups still hidden (pacing incomplete)
      expect(result.current.pacedDisplayGroups.length).toBe(0);

      // Step 4: Advance timer to complete pacing
      act(() => {
        jest.advanceTimersByTime(200);
      });

      // Now pacing is complete → display groups shown again
      expect(result.current.pacedTurnGroups.length).toBe(2);
      expect(result.current.pacedDisplayGroups.length).toBe(1);
    });
  });

  describe("referential stability", () => {
    test("returns same array reference when turn groups have not changed", () => {
      const step1 = createStep(0, 0);

      const { result, rerender } = renderHook(
        ({ turnGroups }) => usePacedTurnGroups(turnGroups, [], false, 1, false),
        { initialProps: { turnGroups: [createTurnGroup([step1])] } }
      );

      // First step revealed immediately
      expect(result.current.pacedTurnGroups.length).toBe(1);

      // Add second step and reveal it via pacing
      const step2 = createStep(1, 0);
      rerender({
        turnGroups: [createTurnGroup([step1]), createTurnGroup([step2])],
      });
      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(2);

      const stableRef = result.current.pacedTurnGroups;

      // Re-render with new array containing structurally identical turn groups
      rerender({
        turnGroups: [createTurnGroup([step1]), createTurnGroup([step2])],
      });

      // Should be the exact same array reference (nothing changed)
      expect(result.current.pacedTurnGroups).toBe(stableRef);
    });

    test("preserves completed group references when streaming group changes", () => {
      const step1 = createStep(0, 0);

      const { result, rerender } = renderHook(
        ({ turnGroups, stopPacketSeen }) =>
          usePacedTurnGroups(turnGroups, [], stopPacketSeen, 1, false),
        {
          initialProps: {
            turnGroups: [createTurnGroup([step1])],
            stopPacketSeen: false,
          },
        }
      );

      // First step revealed immediately
      expect(result.current.pacedTurnGroups.length).toBe(1);

      // Add second step and advance timer to reveal it
      const step2 = createStep(1, 0);
      rerender({
        turnGroups: [createTurnGroup([step1]), createTurnGroup([step2])],
        stopPacketSeen: false,
      });
      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(2);

      const firstGroupRef = result.current.pacedTurnGroups[0];

      // Simulate streaming: step2 gets another item
      const step2Updated: TransformedStep = {
        ...step2,
        items: [...step2.items, toolItem(1, 1)],
      };
      rerender({
        turnGroups: [createTurnGroup([step1]), createTurnGroup([step2Updated])],
        stopPacketSeen: false,
      });

      // First group (completed) should keep the same object reference
      expect(result.current.pacedTurnGroups[0]).toBe(firstGroupRef);
      // Second group changed (items.length differs) — new reference
      expect(result.current.pacedTurnGroups.length).toBe(2);
    });

    test("returns new array reference when a new step is revealed", () => {
      const step1 = createStep(0, 0);

      const { result, rerender } = renderHook(
        ({ turnGroups }) => usePacedTurnGroups(turnGroups, [], false, 1, false),
        { initialProps: { turnGroups: [createTurnGroup([step1])] } }
      );

      const firstResult = result.current.pacedTurnGroups;
      expect(firstResult.length).toBe(1);

      // Add second step and reveal it
      const step2 = createStep(1, 0);
      rerender({
        turnGroups: [createTurnGroup([step1]), createTurnGroup([step2])],
      });
      act(() => {
        jest.advanceTimersByTime(200);
      });

      // Array reference must differ (length changed)
      expect(result.current.pacedTurnGroups).not.toBe(firstResult);
      expect(result.current.pacedTurnGroups.length).toBe(2);
    });
  });

  describe("timer cleanup", () => {
    test("clears timer on unmount", () => {
      const step1 = createStep(0, 0);

      const { result, rerender, unmount } = renderHook(
        ({ turnGroups }) => usePacedTurnGroups(turnGroups, [], false, 1, false),
        { initialProps: { turnGroups: [createTurnGroup([step1])] } }
      );

      // Add second step to create pending timer
      const step2 = createStep(1, 0);
      rerender({
        turnGroups: [createTurnGroup([step1]), createTurnGroup([step2])],
      });

      // Unmount before timer fires
      unmount();

      // Advance timer - should not throw
      act(() => {
        jest.advanceTimersByTime(200);
      });

      // No assertion needed - just verifying no errors on timer fire after unmount
    });

    test("clears timer on nodeId change", () => {
      const step1 = createStep(0, 0);

      const { result, rerender } = renderHook(
        ({ turnGroups, nodeId }) =>
          usePacedTurnGroups(turnGroups, [], false, nodeId, false),
        {
          initialProps: {
            turnGroups: [createTurnGroup([step1])],
            nodeId: 1,
          },
        }
      );

      // Add second step to create pending timer
      const step2 = createStep(1, 0);
      rerender({
        turnGroups: [createTurnGroup([step1]), createTurnGroup([step2])],
        nodeId: 1,
      });

      // Change nodeId - should clear timer
      rerender({
        turnGroups: [createTurnGroup([step1])],
        nodeId: 2,
      });

      // Old timer should not affect new state
      act(() => {
        jest.advanceTimersByTime(200);
      });

      // Only one step for new nodeId
      expect(result.current.pacedTurnGroups.length).toBe(1);
    });
  });
});

test("propagates a terminal item replacement without adding a timeline item", () => {
  const original = toolItem();
  const step: TransformedStep = {
    key: "0-0",
    turnIndex: 0,
    tabIndex: 0,
    items: [original],
  };
  const { result, rerender } = renderHook(
    ({ step }) =>
      usePacedTurnGroups([createTurnGroup([step])], [], false, 1, false),
    { initialProps: { step } }
  );
  expect(
    result.current.pacedTurnGroups[0]?.steps[0]?.items[0]?.content.status
  ).toBe("running");
  const completed = {
    ...original,
    content: { ...original.content, status: "complete" as const },
  };
  rerender({ step: { ...step, items: [completed] } });
  expect(result.current.pacedTurnGroups[0]?.steps[0]?.items[0]).toBe(completed);
});
