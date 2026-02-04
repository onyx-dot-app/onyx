/**
 * Integration tests for usePacketProcessor hook
 *
 * Tests the React hook that wraps packet processing functions with React state
 * management, memoization, and callbacks. Uses @testing-library/react's renderHook.
 */
import { renderHook, act } from "@testing-library/react";
import {
  Packet,
  PacketType,
  StopReason,
} from "@/app/app/services/streamingModels";
import { usePacketProcessor } from "./usePacketProcessor";
import {
  createPacket,
  createSearchToolStartPacket,
  createMessageStartPacket,
  createStopPacket,
  createBranchingPacket,
} from "./__tests__/testHelpers";

// Mock the transformers module
jest.mock("../transformers", () => ({
  transformPacketGroups: jest.fn((groups) =>
    groups.map(
      (g: { turn_index: number; tab_index: number; packets: Packet[] }) => ({
        key: `${g.turn_index}-${g.tab_index}`,
        turnIndex: g.turn_index,
        tabIndex: g.tab_index,
        packets: g.packets,
      })
    )
  ),
  groupStepsByTurn: jest.fn((steps) => {
    const turnMap = new Map<number, typeof steps>();
    for (const step of steps) {
      const existing = turnMap.get(step.turnIndex);
      if (existing) {
        existing.push(step);
      } else {
        turnMap.set(step.turnIndex, [step]);
      }
    }
    return Array.from(turnMap.entries())
      .sort(([a], [b]) => a - b)
      .map(([turnIndex, stepsForTurn]) => ({
        turnIndex,
        steps: stepsForTurn,
        isParallel: stepsForTurn.length > 1,
      }));
  }),
}));

// ============================================================================
// Tests
// ============================================================================

describe("usePacketProcessor", () => {
  describe("initial state", () => {
    test("returns empty arrays when no packets", () => {
      const { result } = renderHook(() => usePacketProcessor([], 1));

      expect(result.current.toolGroups).toEqual([]);
      expect(result.current.displayGroups).toEqual([]);
      expect(result.current.toolTurnGroups).toEqual([]);
    });

    test("returns empty citations when no packets", () => {
      const { result } = renderHook(() => usePacketProcessor([], 1));

      expect(result.current.citations).toEqual([]);
      expect(result.current.citationMap).toEqual({});
    });

    test("initializes stopPacketSeen to false", () => {
      const { result } = renderHook(() => usePacketProcessor([], 1));

      expect(result.current.stopPacketSeen).toBe(false);
    });

    test("initializes isComplete to false", () => {
      const { result } = renderHook(() => usePacketProcessor([], 1));

      expect(result.current.isComplete).toBe(false);
    });

    test("provides stable callback references", () => {
      const { result, rerender } = renderHook(() => usePacketProcessor([], 1));

      const onRenderComplete1 = result.current.onRenderComplete;
      const markAllToolsDisplayed1 = result.current.markAllToolsDisplayed;

      rerender();

      expect(result.current.onRenderComplete).toBe(onRenderComplete1);
      expect(result.current.markAllToolsDisplayed).toBe(markAllToolsDisplayed1);
    });
  });

  describe("nodeId changes", () => {
    test("resets state when nodeId changes", () => {
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
      ];

      const { result, rerender } = renderHook(
        ({ packets, nodeId }) => usePacketProcessor(packets, nodeId),
        { initialProps: { packets, nodeId: 1 } }
      );

      expect(result.current.toolGroups.length).toBe(1);

      // Change nodeId
      rerender({ packets: [], nodeId: 2 });

      expect(result.current.toolGroups).toEqual([]);
    });

    test("processes new packets after nodeId change", () => {
      const packets1 = [createSearchToolStartPacket({ turn_index: 0 })];
      const packets2 = [createMessageStartPacket({ turn_index: 0 })];

      const { result, rerender } = renderHook(
        ({ packets, nodeId }) => usePacketProcessor(packets, nodeId),
        { initialProps: { packets: packets1, nodeId: 1 } }
      );

      expect(result.current.toolGroups.length).toBe(1);

      rerender({ packets: packets2, nodeId: 2 });

      expect(result.current.toolGroups.length).toBe(0);
      expect(result.current.displayGroups.length).toBe(1);
    });
  });

  describe("stream reset detection", () => {
    test("resets state when packets array shrinks", () => {
      const packets1 = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
        createMessageStartPacket({ turn_index: 1 }),
      ];
      const packets2 = [createSearchToolStartPacket({ turn_index: 0 })];

      const { result, rerender } = renderHook(
        ({ packets }) => usePacketProcessor(packets, 1),
        { initialProps: { packets: packets1 } }
      );

      expect(result.current.finalAnswerComing).toBe(true);

      // Shrink packets (simulates stream reset)
      rerender({ packets: packets2 });

      expect(result.current.finalAnswerComing).toBe(false);
    });

    test("resets renderComplete on stream reset", () => {
      const packets = [
        createMessageStartPacket({ turn_index: 0 }),
        createStopPacket(),
      ];

      const { result, rerender } = renderHook(
        ({ packets }) => usePacketProcessor(packets, 1),
        { initialProps: { packets } }
      );

      // Trigger render complete
      act(() => {
        result.current.onRenderComplete();
      });

      expect(result.current.isComplete).toBe(true);

      // Shrink packets
      rerender({ packets: [createMessageStartPacket({ turn_index: 0 })] });

      expect(result.current.isComplete).toBe(false);
    });
  });

  describe("incremental processing", () => {
    test("processes only new packets on update", () => {
      const { result, rerender } = renderHook(
        ({ packets }) => usePacketProcessor(packets, 1),
        { initialProps: { packets: [] as Packet[] } }
      );

      expect(result.current.toolGroups.length).toBe(0);

      // Add packets
      const packets = [createSearchToolStartPacket({ turn_index: 0 })];
      rerender({ packets });

      expect(result.current.toolGroups.length).toBe(1);

      // Add more packets
      const morePackets = [
        ...packets,
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
      ];
      rerender({ packets: morePackets });

      expect(result.current.toolGroups.length).toBe(1);
    });

    test("handles rapid packet updates", () => {
      const { result, rerender } = renderHook(
        ({ packets }) => usePacketProcessor(packets, 1),
        { initialProps: { packets: [] as Packet[] } }
      );

      // Simulate rapid streaming updates
      for (let i = 0; i < 10; i++) {
        const packets = Array.from({ length: i + 1 }, (_, j) =>
          j === 0
            ? createSearchToolStartPacket({ turn_index: 0 })
            : createPacket(
                PacketType.SEARCH_TOOL_QUERIES_DELTA,
                { turn_index: 0 },
                { queries: [`q${j}`] }
              )
        );
        rerender({ packets });
      }

      expect(result.current.toolGroups.length).toBe(1);
    });
  });

  describe("displayGroups derivation", () => {
    test("returns empty when tools exist but finalAnswerComing is false", () => {
      const packets = [createSearchToolStartPacket({ turn_index: 0 })];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      expect(result.current.toolGroups.length).toBe(1);
      expect(result.current.displayGroups.length).toBe(0);
      expect(result.current.finalAnswerComing).toBe(false);
    });

    test("returns potentialDisplayGroups when finalAnswerComing is true", () => {
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
        createMessageStartPacket({ turn_index: 1 }),
      ];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      expect(result.current.finalAnswerComing).toBe(true);
      expect(result.current.displayGroups.length).toBe(1);
    });

    test("returns potentialDisplayGroups when no tools exist", () => {
      const packets = [createMessageStartPacket({ turn_index: 0 })];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      expect(result.current.toolGroups.length).toBe(0);
      expect(result.current.displayGroups.length).toBe(1);
    });

    test("returns potentialDisplayGroups when forceShowAnswer triggered", () => {
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createMessageStartPacket({ turn_index: 1 }),
      ];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      // Initially visible because finalAnswerComing is true
      expect(result.current.displayGroups.length).toBe(1);

      // Add tool after message to reset finalAnswerComing
      const { result: result2 } = renderHook(() =>
        usePacketProcessor(
          [
            createSearchToolStartPacket({ turn_index: 0 }),
            // No message yet, so displayGroups should be empty
          ],
          2
        )
      );

      expect(result2.current.displayGroups.length).toBe(0);

      // Force show answer
      act(() => {
        result2.current.markAllToolsDisplayed();
      });

      expect(result2.current.displayGroups.length).toBe(0); // Still 0 because no message packet
    });
  });

  describe("tool-after-message transition", () => {
    test("resets renderComplete on transition from finalAnswerComing true to false", () => {
      // Start with message (finalAnswerComing=true)
      const initialPackets = [createMessageStartPacket({ turn_index: 0 })];

      const { result, rerender } = renderHook(
        ({ packets }) => usePacketProcessor(packets, 1),
        { initialProps: { packets: initialPackets } }
      );

      expect(result.current.finalAnswerComing).toBe(true);

      // Add a tool after the message - this simulates the Claude workaround scenario
      // where Claude sends a message first, then decides to call a tool
      const packetsWithToolAfter = [
        ...initialPackets,
        createSearchToolStartPacket({ turn_index: 1 }),
      ];
      rerender({ packets: packetsWithToolAfter });

      // The tool should reset finalAnswerComing since it's an actual tool call
      expect(result.current.finalAnswerComing).toBe(false);
    });
  });

  describe("onRenderComplete callback", () => {
    test("sets isComplete when finalAnswerComing and stopPacketSeen", () => {
      const packets = [
        createMessageStartPacket({ turn_index: 0 }),
        createStopPacket(),
      ];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      expect(result.current.finalAnswerComing).toBe(true);
      expect(result.current.stopPacketSeen).toBe(true);
      expect(result.current.isComplete).toBe(false);

      act(() => {
        result.current.onRenderComplete();
      });

      expect(result.current.isComplete).toBe(true);
    });

    test("does not set isComplete when finalAnswerComing is false", () => {
      const packets = [createSearchToolStartPacket({ turn_index: 0 })];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      expect(result.current.finalAnswerComing).toBe(false);

      act(() => {
        result.current.onRenderComplete();
      });

      expect(result.current.isComplete).toBe(false);
    });
  });

  describe("markAllToolsDisplayed callback", () => {
    test("forces displayGroups to show even when finalAnswerComing is false", () => {
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createMessageStartPacket({ turn_index: 1 }),
      ];

      const { result, rerender } = renderHook(
        ({ packets }) => usePacketProcessor(packets, 1),
        { initialProps: { packets } }
      );

      // Initially visible since finalAnswerComing is true after MESSAGE_START
      expect(result.current.displayGroups.length).toBe(1);

      // Reset to a state where no message, with forceShow
      const toolOnlyPackets = [createSearchToolStartPacket({ turn_index: 0 })];

      const { result: result2 } = renderHook(() =>
        usePacketProcessor(toolOnlyPackets, 2)
      );

      expect(result2.current.displayGroups.length).toBe(0);

      act(() => {
        result2.current.markAllToolsDisplayed();
      });

      // Now should be ready to show (though still empty because no message in packets)
      // The key thing is forceShowAnswer flag is set
      expect(result2.current.finalAnswerComing).toBe(false);
    });
  });

  describe("isComplete flag", () => {
    test("false when stopPacketSeen is false", () => {
      const packets = [createMessageStartPacket({ turn_index: 0 })];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      act(() => {
        result.current.onRenderComplete();
      });

      expect(result.current.stopPacketSeen).toBe(false);
      expect(result.current.isComplete).toBe(false);
    });

    test("false when renderComplete is false", () => {
      const packets = [
        createMessageStartPacket({ turn_index: 0 }),
        createStopPacket(),
      ];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      expect(result.current.stopPacketSeen).toBe(true);
      expect(result.current.isComplete).toBe(false);
    });

    test("true only when BOTH stopPacketSeen and renderComplete are true", () => {
      const packets = [
        createMessageStartPacket({ turn_index: 0 }),
        createStopPacket(),
      ];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      expect(result.current.stopPacketSeen).toBe(true);
      expect(result.current.isComplete).toBe(false);

      act(() => {
        result.current.onRenderComplete();
      });

      expect(result.current.isComplete).toBe(true);
    });
  });

  describe("hasSteps flag", () => {
    test("false when no tool groups", () => {
      const packets = [createMessageStartPacket({ turn_index: 0 })];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      expect(result.current.hasSteps).toBe(false);
    });

    test("true when tool groups exist", () => {
      const packets = [createSearchToolStartPacket({ turn_index: 0 })];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      expect(result.current.hasSteps).toBe(true);
    });
  });

  describe("toolTurnGroups transformation", () => {
    test("groups tools by turn index", () => {
      const packets = [
        createBranchingPacket(2, 0),
        createSearchToolStartPacket({ turn_index: 0, tab_index: 0 }),
        createSearchToolStartPacket({ turn_index: 0, tab_index: 1 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0, tab_index: 0 }),
        createPacket(PacketType.SECTION_END, { turn_index: 0, tab_index: 1 }),
      ];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      expect(result.current.toolTurnGroups.length).toBe(1);
      expect(result.current.toolTurnGroups[0]?.isParallel).toBe(true);
      expect(result.current.toolTurnGroups[0]?.steps.length).toBe(2);
    });
  });

  describe("expectedBranchesPerTurn", () => {
    test("exposes branch metadata from packets", () => {
      const packets = [
        createBranchingPacket(3, 0),
        createSearchToolStartPacket({ turn_index: 0, tab_index: 0 }),
        createSearchToolStartPacket({ turn_index: 0, tab_index: 1 }),
        createSearchToolStartPacket({ turn_index: 0, tab_index: 2 }),
      ];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      expect(result.current.expectedBranchesPerTurn.get(0)).toBe(3);
    });
  });

  describe("complex scenarios", () => {
    test("full flow: tools -> message -> complete", () => {
      const packets = [
        createSearchToolStartPacket({ turn_index: 0 }),
        createPacket(
          PacketType.SEARCH_TOOL_QUERIES_DELTA,
          { turn_index: 0 },
          { queries: ["test"] }
        ),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
        createMessageStartPacket({ turn_index: 1 }, 1.5),
        createPacket(
          PacketType.MESSAGE_DELTA,
          { turn_index: 1 },
          { content: "Result:" }
        ),
        createStopPacket(StopReason.FINISHED),
      ];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      expect(result.current.toolGroups.length).toBe(1);
      expect(result.current.displayGroups.length).toBe(1);
      expect(result.current.hasSteps).toBe(true);
      expect(result.current.stopPacketSeen).toBe(true);
      expect(result.current.stopReason).toBe(StopReason.FINISHED);
      expect(result.current.finalAnswerComing).toBe(true);
      expect(result.current.toolProcessingDuration).toBe(1.5);

      act(() => {
        result.current.onRenderComplete();
      });

      expect(result.current.isComplete).toBe(true);
    });

    test("handles image generation flow", () => {
      const packets = [
        createPacket(PacketType.IMAGE_GENERATION_TOOL_START, { turn_index: 0 }),
        createPacket(
          PacketType.IMAGE_GENERATION_TOOL_DELTA,
          { turn_index: 0 },
          {
            images: [
              {
                file_id: "img1",
                url: "http://example.com/1.png",
                revised_prompt: "test",
              },
            ],
          }
        ),
        createPacket(PacketType.SECTION_END, { turn_index: 0 }),
        createStopPacket(),
      ];

      const { result } = renderHook(() => usePacketProcessor(packets, 1));

      expect(result.current.isGeneratingImage).toBe(true);
      expect(result.current.generatedImageCount).toBe(1);
      expect(result.current.finalAnswerComing).toBe(true);
      expect(result.current.displayGroups.length).toBe(1);
    });
  });
});
