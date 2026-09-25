import { act, renderHook } from "@testing-library/react-native";
import { describe, expect, it } from "@jest/globals";

import { StopReason, type Packet } from "@/chat/streamingModels";
import { usePacketProcessor } from "@/hooks/timeline/usePacketProcessor";

import { makePlacedPacket } from "../../../chat/__tests__/fixtures";

// packet builders (mirror grouping.test.ts)
const searchStart = (turn: number, tab = 0): Packet =>
  makePlacedPacket(
    { type: "search_tool_start", is_internet_search: false },
    { turn_index: turn, tab_index: tab },
  );
const searchQueriesDelta = (turn: number, tab = 0): Packet =>
  makePlacedPacket(
    { type: "search_tool_queries_delta", queries: ["q"] },
    { turn_index: turn, tab_index: tab },
  );
const sectionEnd = (turn: number, tab = 0): Packet =>
  makePlacedPacket(
    { type: "section_end" },
    { turn_index: turn, tab_index: tab },
  );
const messageStart = (turn: number, preSeconds?: number): Packet =>
  makePlacedPacket(
    {
      type: "message_start",
      id: "m",
      content: "",
      final_documents: null,
      ...(preSeconds !== undefined
        ? { pre_answer_processing_seconds: preSeconds }
        : {}),
    },
    { turn_index: turn },
  );
const messageDelta = (turn: number, content: string): Packet =>
  makePlacedPacket({ type: "message_delta", content }, { turn_index: turn });
const stopAt = (reason: StopReason = StopReason.FINISHED): Packet =>
  makePlacedPacket({ type: "stop", stop_reason: reason }, { turn_index: 0 });
const branching = (n: number, turn: number): Packet =>
  makePlacedPacket(
    { type: "top_level_branching", num_parallel_branches: n },
    { turn_index: turn },
  );
const imageStart = (turn: number): Packet =>
  makePlacedPacket({ type: "image_generation_start" }, { turn_index: turn });
const imageFinal = (turn: number): Packet =>
  makePlacedPacket(
    {
      type: "image_generation_final",
      images: [{ file_id: "a", url: "u", revised_prompt: "p" }],
    },
    { turn_index: turn },
  );

describe("usePacketProcessor", () => {
  describe("initial state", () => {
    it("returns empty data with no packets", () => {
      const { result } = renderHook(() => usePacketProcessor([], 1));
      expect(result.current.toolGroups).toEqual([]);
      expect(result.current.displayGroups).toEqual([]);
      expect(result.current.toolTurnGroups).toEqual([]);
      expect(result.current.citations).toEqual([]);
      expect(result.current.citationMap).toEqual({});
      expect(result.current.stopPacketSeen).toBe(false);
      expect(result.current.isComplete).toBe(false);
    });

    it("provides stable callback references across rerenders", () => {
      const { result, rerender } = renderHook(
        ({ packets }: { packets: Packet[] }) => usePacketProcessor(packets, 1),
        { initialProps: { packets: [] as Packet[] } },
      );
      const onRenderComplete1 = result.current.onRenderComplete;
      const markAllToolsDisplayed1 = result.current.markAllToolsDisplayed;
      rerender({ packets: [] as Packet[] });
      expect(result.current.onRenderComplete).toBe(onRenderComplete1);
      expect(result.current.markAllToolsDisplayed).toBe(markAllToolsDisplayed1);
    });
  });

  describe("nodeId changes", () => {
    it("resets derived data when nodeId changes", () => {
      const { result, rerender } = renderHook(
        ({ packets, nodeId }: { packets: Packet[]; nodeId: number }) =>
          usePacketProcessor(packets, nodeId),
        {
          initialProps: {
            packets: [searchStart(0), sectionEnd(0)],
            nodeId: 1,
          },
        },
      );
      expect(result.current.toolGroups.length).toBe(1);

      rerender({ packets: [] as Packet[], nodeId: 2 });
      expect(result.current.toolGroups).toEqual([]);
    });

    it("processes new packets after a nodeId change", () => {
      const { result, rerender } = renderHook(
        ({ packets, nodeId }: { packets: Packet[]; nodeId: number }) =>
          usePacketProcessor(packets, nodeId),
        { initialProps: { packets: [searchStart(0)], nodeId: 1 } },
      );
      expect(result.current.toolGroups.length).toBe(1);

      rerender({ packets: [messageStart(0)], nodeId: 2 });
      expect(result.current.toolGroups.length).toBe(0);
      expect(result.current.displayGroups.length).toBe(1);
    });
  });

  describe("stream reset detection", () => {
    it("rebuilds when the packets array shrinks", () => {
      const { result, rerender } = renderHook(
        ({ packets }: { packets: Packet[] }) => usePacketProcessor(packets, 1),
        {
          initialProps: {
            packets: [searchStart(0), sectionEnd(0), messageStart(1)],
          },
        },
      );
      expect(result.current.finalAnswerComing).toBe(true);

      rerender({ packets: [searchStart(0)] });
      expect(result.current.finalAnswerComing).toBe(false);
    });
  });

  describe("displayGroups derivation", () => {
    it("hides display groups while tools exist and no answer is coming", () => {
      const { result } = renderHook(() =>
        usePacketProcessor([searchStart(0)], 1),
      );
      expect(result.current.toolGroups.length).toBe(1);
      expect(result.current.finalAnswerComing).toBe(false);
      expect(result.current.displayGroups.length).toBe(0);
    });

    it("shows display groups once the answer is coming", () => {
      const { result } = renderHook(() =>
        usePacketProcessor([searchStart(0), sectionEnd(0), messageStart(1)], 1),
      );
      expect(result.current.finalAnswerComing).toBe(true);
      expect(result.current.displayGroups.length).toBe(1);
    });

    it("shows display groups immediately when there were no tools", () => {
      const { result } = renderHook(() =>
        usePacketProcessor([messageStart(0)], 1),
      );
      expect(result.current.toolGroups.length).toBe(0);
      expect(result.current.displayGroups.length).toBe(1);
    });
  });

  describe("tool-after-message transition", () => {
    it("retracts finalAnswerComing when a real tool follows the message", () => {
      const { result, rerender } = renderHook(
        ({ packets }: { packets: Packet[] }) => usePacketProcessor(packets, 1),
        { initialProps: { packets: [messageStart(0)] } },
      );
      expect(result.current.finalAnswerComing).toBe(true);

      rerender({ packets: [messageStart(0), searchStart(1)] });
      expect(result.current.finalAnswerComing).toBe(false);
    });
  });

  describe("completion", () => {
    it("sets isComplete only after onRenderComplete when final answer + stop seen", () => {
      const { result } = renderHook(() =>
        usePacketProcessor([messageStart(0), stopAt()], 1),
      );
      expect(result.current.finalAnswerComing).toBe(true);
      expect(result.current.stopPacketSeen).toBe(true);
      expect(result.current.isComplete).toBe(false);

      act(() => {
        result.current.onRenderComplete();
      });
      expect(result.current.isComplete).toBe(true);
    });

    it("does not complete when the final answer is not coming", () => {
      const { result } = renderHook(() =>
        usePacketProcessor([searchStart(0)], 1),
      );
      expect(result.current.finalAnswerComing).toBe(false);

      act(() => {
        result.current.onRenderComplete();
      });
      expect(result.current.isComplete).toBe(false);
    });

    it("stays incomplete when stop has not been seen", () => {
      const { result } = renderHook(() =>
        usePacketProcessor([messageStart(0)], 1),
      );
      act(() => {
        result.current.onRenderComplete();
      });
      expect(result.current.stopPacketSeen).toBe(false);
      expect(result.current.isComplete).toBe(false);
    });
  });

  describe("hasSteps + branches", () => {
    it("reports hasSteps false with no tool groups", () => {
      const { result } = renderHook(() =>
        usePacketProcessor([messageStart(0)], 1),
      );
      expect(result.current.hasSteps).toBe(false);
    });

    it("reports hasSteps true with tool groups", () => {
      const { result } = renderHook(() =>
        usePacketProcessor([searchStart(0)], 1),
      );
      expect(result.current.hasSteps).toBe(true);
    });

    it("groups parallel tools into one turn group and exposes branch metadata", () => {
      const { result } = renderHook(() =>
        usePacketProcessor(
          [
            branching(2, 0),
            searchStart(0, 0),
            searchStart(0, 1),
            sectionEnd(0, 0),
            sectionEnd(0, 1),
          ],
          1,
        ),
      );
      expect(result.current.toolTurnGroups.length).toBe(1);
      expect(result.current.toolTurnGroups[0]?.isParallel).toBe(true);
      expect(result.current.toolTurnGroups[0]?.steps.length).toBe(2);
      expect(result.current.expectedBranchesPerTurn.get(0)).toBe(2);
    });
  });

  describe("full flows", () => {
    it("tools → message → complete", () => {
      const { result } = renderHook(() =>
        usePacketProcessor(
          [
            searchStart(0),
            searchQueriesDelta(0),
            sectionEnd(0),
            messageStart(1, 1.5),
            messageDelta(1, "Result:"),
            stopAt(StopReason.FINISHED),
          ],
          1,
        ),
      );
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

    it("image generation flow", () => {
      const { result } = renderHook(() =>
        usePacketProcessor(
          [imageStart(0), imageFinal(0), sectionEnd(0), stopAt()],
          1,
        ),
      );
      expect(result.current.isGeneratingImage).toBe(true);
      expect(result.current.generatedImageCount).toBe(1);
      expect(result.current.finalAnswerComing).toBe(true);
      expect(result.current.displayGroups.length).toBe(1);
    });
  });
});
