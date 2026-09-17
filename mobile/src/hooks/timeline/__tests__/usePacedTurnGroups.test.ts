import { act, renderHook } from "@testing-library/react-native";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";

import { GroupedPacket } from "@/chat/messageProcessor";
import { PacketType, type Packet } from "@/chat/streamingModels";
import { TransformedStep, TurnGroup } from "@/chat/timeline/transformers";
import { usePacedTurnGroups } from "@/hooks/timeline/usePacedTurnGroups";

function createStep(
  turnIndex: number,
  tabIndex: number,
  type: PacketType = PacketType.SEARCH_TOOL_START,
): TransformedStep {
  return {
    key: `${turnIndex}-${tabIndex}`,
    turnIndex,
    tabIndex,
    packets: [
      {
        placement: { turn_index: turnIndex, tab_index: tabIndex },
        obj: { type },
      } as Packet,
    ],
  };
}

function createTurnGroup(steps: TransformedStep[]): TurnGroup {
  return {
    turnIndex: steps[0]!.turnIndex,
    steps,
    isParallel: steps.length > 1,
  };
}

function createDisplayGroup(turnIndex: number): GroupedPacket {
  return {
    turn_index: turnIndex,
    tab_index: 0,
    packets: [
      {
        placement: { turn_index: turnIndex, tab_index: 0 },
        obj: {
          type: PacketType.MESSAGE_START,
          id: "m",
          content: "",
          final_documents: null,
        },
      } as Packet,
    ],
  };
}

describe("usePacedTurnGroups", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  describe("initial state", () => {
    it("returns empty arrays with no turn groups", () => {
      const { result } = renderHook(() =>
        usePacedTurnGroups([], [], false, 1, false),
      );
      expect(result.current.pacedTurnGroups).toEqual([]);
      expect(result.current.pacedDisplayGroups).toEqual([]);
      expect(result.current.pacedFinalAnswerComing).toBe(false);
    });
  });

  describe("history bypass", () => {
    it("reveals everything immediately when stop is seen on first render", () => {
      const turnGroups = [
        createTurnGroup([createStep(0, 0)]),
        createTurnGroup([createStep(1, 0)]),
      ];
      const displayGroups = [createDisplayGroup(2)];

      const { result } = renderHook(() =>
        usePacedTurnGroups(turnGroups, displayGroups, true, 1, true),
      );

      expect(result.current.pacedTurnGroups.length).toBe(2);
      expect(result.current.pacedDisplayGroups.length).toBe(1);
      expect(result.current.pacedFinalAnswerComing).toBe(true);
    });
  });

  describe("step pacing", () => {
    it("reveals the first step immediately", () => {
      const { result } = renderHook(() =>
        usePacedTurnGroups(
          [createTurnGroup([createStep(0, 0)])],
          [],
          false,
          1,
          false,
        ),
      );
      expect(result.current.pacedTurnGroups.length).toBe(1);
      expect(result.current.pacedTurnGroups[0]?.steps[0]?.key).toBe("0-0");
    });

    it("reveals subsequent steps 200ms apart", () => {
      const { result, rerender } = renderHook(
        ({ turnGroups }: { turnGroups: TurnGroup[] }) =>
          usePacedTurnGroups(turnGroups, [], false, 1, false),
        { initialProps: { turnGroups: [createTurnGroup([createStep(0, 0)])] } },
      );
      expect(result.current.pacedTurnGroups.length).toBe(1);

      rerender({
        turnGroups: [
          createTurnGroup([createStep(0, 0)]),
          createTurnGroup([createStep(1, 0)]),
          createTurnGroup([createStep(2, 0)]),
        ],
      });
      // Second and third steps queued, not yet revealed.
      expect(result.current.pacedTurnGroups.length).toBe(1);

      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(2);

      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(3);
    });

    it("paces same-type steps with a delay (does not batch)", () => {
      const { result, rerender } = renderHook(
        ({ turnGroups }: { turnGroups: TurnGroup[] }) =>
          usePacedTurnGroups(turnGroups, [], false, 1, false),
        {
          initialProps: {
            turnGroups: [
              createTurnGroup([createStep(0, 0, PacketType.SEARCH_TOOL_START)]),
            ],
          },
        },
      );
      rerender({
        turnGroups: [
          createTurnGroup([createStep(0, 0, PacketType.SEARCH_TOOL_START)]),
          createTurnGroup([createStep(1, 0, PacketType.SEARCH_TOOL_START)]),
        ],
      });
      expect(result.current.pacedTurnGroups.length).toBe(1);

      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(2);
    });
  });

  describe("stop packet", () => {
    it("flushes all pending steps immediately", () => {
      const { result, rerender } = renderHook(
        ({
          turnGroups,
          stopPacketSeen,
        }: {
          turnGroups: TurnGroup[];
          stopPacketSeen: boolean;
        }) => usePacedTurnGroups(turnGroups, [], stopPacketSeen, 1, false),
        {
          initialProps: {
            turnGroups: [createTurnGroup([createStep(0, 0)])],
            stopPacketSeen: false,
          },
        },
      );
      expect(result.current.pacedTurnGroups.length).toBe(1);

      rerender({
        turnGroups: [
          createTurnGroup([createStep(0, 0)]),
          createTurnGroup([createStep(1, 0)]),
          createTurnGroup([createStep(2, 0)]),
        ],
        stopPacketSeen: false,
      });
      expect(result.current.pacedTurnGroups.length).toBe(1);

      rerender({
        turnGroups: [
          createTurnGroup([createStep(0, 0)]),
          createTurnGroup([createStep(1, 0)]),
          createTurnGroup([createStep(2, 0)]),
        ],
        stopPacketSeen: true,
      });
      expect(result.current.pacedTurnGroups.length).toBe(3);
    });
  });

  describe("display groups", () => {
    it("shows display groups only after tool pacing completes", () => {
      const displayGroup = createDisplayGroup(1);
      const { result, rerender } = renderHook(
        ({ turnGroups }: { turnGroups: TurnGroup[] }) =>
          usePacedTurnGroups(turnGroups, [displayGroup], false, 1, true),
        { initialProps: { turnGroups: [createTurnGroup([createStep(0, 0)])] } },
      );
      expect(result.current.pacedTurnGroups.length).toBe(1);

      rerender({
        turnGroups: [
          createTurnGroup([createStep(0, 0)]),
          createTurnGroup([createStep(1, 0)]),
        ],
      });
      expect(result.current.pacedDisplayGroups.length).toBe(0);

      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(2);
      expect(result.current.pacedDisplayGroups.length).toBe(1);
    });

    it("re-hides display when a new step queues after pacing had completed", () => {
      // Regression: toolPacingComplete going true→false (a queued step) must publish, so the answer
      // can't show through the pacing gap before the 200ms timer fires.
      const displayGroup = createDisplayGroup(2);
      const { result, rerender } = renderHook(
        ({ turnGroups }: { turnGroups: TurnGroup[] }) =>
          usePacedTurnGroups(turnGroups, [displayGroup], false, 1, true),
        { initialProps: { turnGroups: [createTurnGroup([createStep(0, 0)])] } },
      );

      // Reveal a second step and let pacing complete → answer shown.
      rerender({
        turnGroups: [
          createTurnGroup([createStep(0, 0)]),
          createTurnGroup([createStep(1, 0)]),
        ],
      });
      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedDisplayGroups.length).toBe(1);

      // A third step queues behind the timer — the answer must hide again immediately.
      rerender({
        turnGroups: [
          createTurnGroup([createStep(0, 0)]),
          createTurnGroup([createStep(1, 0)]),
          createTurnGroup([createStep(2, 0)]),
        ],
      });
      expect(result.current.pacedDisplayGroups.length).toBe(0);
      expect(result.current.pacedFinalAnswerComing).toBe(false);

      // Once it reveals, pacing completes and the answer returns.
      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(3);
      expect(result.current.pacedDisplayGroups.length).toBe(1);
    });

    it("shows display groups immediately when there are no tool steps", () => {
      const { result } = renderHook(() =>
        usePacedTurnGroups([], [createDisplayGroup(0)], false, 1, true),
      );
      expect(result.current.pacedDisplayGroups.length).toBe(1);
      expect(result.current.pacedFinalAnswerComing).toBe(true);
    });
  });

  describe("pacedFinalAnswerComing", () => {
    it("is false until tool pacing completes", () => {
      const { result, rerender } = renderHook(
        ({ turnGroups }: { turnGroups: TurnGroup[] }) =>
          usePacedTurnGroups(turnGroups, [], false, 1, true),
        { initialProps: { turnGroups: [createTurnGroup([createStep(0, 0)])] } },
      );
      rerender({
        turnGroups: [
          createTurnGroup([createStep(0, 0)]),
          createTurnGroup([createStep(1, 0)]),
        ],
      });
      expect(result.current.pacedFinalAnswerComing).toBe(false);

      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedFinalAnswerComing).toBe(true);
    });
  });

  describe("tool-after-message transition", () => {
    it("re-hides display when the agent switches from message back to tools", () => {
      const displayGroup = createDisplayGroup(0);
      const { result, rerender } = renderHook(
        ({
          turnGroups,
          finalAnswerComing,
        }: {
          turnGroups: TurnGroup[];
          finalAnswerComing: boolean;
        }) =>
          usePacedTurnGroups(
            turnGroups,
            [displayGroup],
            false,
            1,
            finalAnswerComing,
          ),
        {
          initialProps: {
            turnGroups: [] as TurnGroup[],
            finalAnswerComing: true,
          },
        },
      );
      // No tools + answer coming → display shown.
      expect(result.current.pacedDisplayGroups.length).toBe(1);
      expect(result.current.pacedFinalAnswerComing).toBe(true);

      // Answer retracted + a new tool starts → display hidden again.
      rerender({
        turnGroups: [createTurnGroup([createStep(0, 0)])],
        finalAnswerComing: false,
      });
      expect(result.current.pacedTurnGroups.length).toBe(1);
      expect(result.current.pacedDisplayGroups.length).toBe(0);

      // Second tool step keeps pacing incomplete.
      rerender({
        turnGroups: [
          createTurnGroup([createStep(0, 0)]),
          createTurnGroup([createStep(1, 0)]),
        ],
        finalAnswerComing: false,
      });
      expect(result.current.pacedDisplayGroups.length).toBe(0);

      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(2);
      expect(result.current.pacedDisplayGroups.length).toBe(1);
    });
  });

  describe("nodeId reset", () => {
    it("resets pacing state when nodeId changes", () => {
      const { result, rerender } = renderHook(
        ({ nodeId }: { nodeId: number }) =>
          usePacedTurnGroups(
            [createTurnGroup([createStep(0, 0)])],
            [],
            false,
            nodeId,
            false,
          ),
        { initialProps: { nodeId: 1 } },
      );
      expect(result.current.pacedTurnGroups.length).toBe(1);

      rerender({ nodeId: 2 });
      expect(result.current.pacedTurnGroups.length).toBe(1);
    });

    it("does not carry a prior node's revealed steps into a new node", () => {
      const { result, rerender } = renderHook(
        ({ turnGroups, nodeId }: { turnGroups: TurnGroup[]; nodeId: number }) =>
          usePacedTurnGroups(turnGroups, [], false, nodeId, false),
        {
          initialProps: {
            turnGroups: [createTurnGroup([createStep(0, 0)])],
            nodeId: 1,
          },
        },
      );
      expect(result.current.pacedTurnGroups[0]?.steps[0]?.key).toBe("0-0");

      // New node whose only step has a different key — the prior "0-0" must not leak through.
      rerender({
        turnGroups: [createTurnGroup([createStep(5, 0)])],
        nodeId: 2,
      });
      expect(result.current.pacedTurnGroups.length).toBe(1);
      expect(result.current.pacedTurnGroups[0]?.steps[0]?.key).toBe("5-0");
    });
  });

  describe("timer cleanup", () => {
    it("clears the timer on unmount without throwing", () => {
      const { rerender, unmount } = renderHook(
        ({ turnGroups }: { turnGroups: TurnGroup[] }) =>
          usePacedTurnGroups(turnGroups, [], false, 1, false),
        { initialProps: { turnGroups: [createTurnGroup([createStep(0, 0)])] } },
      );
      rerender({
        turnGroups: [
          createTurnGroup([createStep(0, 0)]),
          createTurnGroup([createStep(1, 0)]),
        ],
      });
      unmount();
      act(() => {
        jest.advanceTimersByTime(200);
      });
    });

    it("clears a pending timer when nodeId changes", () => {
      const { result, rerender } = renderHook(
        ({ turnGroups, nodeId }: { turnGroups: TurnGroup[]; nodeId: number }) =>
          usePacedTurnGroups(turnGroups, [], false, nodeId, false),
        {
          initialProps: {
            turnGroups: [createTurnGroup([createStep(0, 0)])],
            nodeId: 1,
          },
        },
      );
      rerender({
        turnGroups: [
          createTurnGroup([createStep(0, 0)]),
          createTurnGroup([createStep(1, 0)]),
        ],
        nodeId: 1,
      });
      rerender({
        turnGroups: [createTurnGroup([createStep(0, 0)])],
        nodeId: 2,
      });
      act(() => {
        jest.advanceTimersByTime(200);
      });
      expect(result.current.pacedTurnGroups.length).toBe(1);
    });
  });
});
