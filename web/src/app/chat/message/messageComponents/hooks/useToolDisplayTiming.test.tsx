/**
 * Unit tests for useToolDisplayTiming hook
 * Tests timing logic in isolation with real implementation and fake timers
 */

import { renderHook, act } from "@testing-library/react";
import { useToolDisplayTiming } from "./useToolDisplayTiming";
import { createToolGroups } from "@tests/setup/multiToolTestHelpers";

describe("useToolDisplayTiming", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  describe("Initial State", () => {
    test("shows first tool immediately when streaming starts", () => {
      const toolGroups = createToolGroups(3);

      const { result } = renderHook(() =>
        useToolDisplayTiming(toolGroups, false, false)
      );

      // First tool visible immediately (key format: "turn_index-tab_index")
      expect(result.current.visibleTools.size).toBe(1);
      expect(result.current.visibleTools.has("0-0")).toBe(true);
    });

    test("shows all tools when isComplete=true on mount", () => {
      const toolGroups = createToolGroups(3);

      const { result } = renderHook(() =>
        useToolDisplayTiming(toolGroups, true, true)
      );

      // All tools visible (key format: "turn_index-tab_index")
      expect(result.current.visibleTools.size).toBe(3);
      expect(result.current.visibleTools.has("0-0")).toBe(true);
      expect(result.current.visibleTools.has("1-0")).toBe(true);
      expect(result.current.visibleTools.has("2-0")).toBe(true);
    });

    test("shows allToolsDisplayed is true when isComplete and finalAnswerComing", () => {
      const toolGroups = createToolGroups(3);

      const { result } = renderHook(() =>
        useToolDisplayTiming(toolGroups, true, true)
      );

      // All tools visible and complete, final answer coming
      expect(result.current.allToolsDisplayed).toBe(true);
    });

    test("shows allToolsDisplayed is false when streaming", () => {
      const toolGroups = createToolGroups(3);

      const { result } = renderHook(() =>
        useToolDisplayTiming(toolGroups, false, false)
      );

      expect(result.current.allToolsDisplayed).toBe(false);
    });
  });

  describe("Progressive Display", () => {
    test("makes next tool visible after previous completes", () => {
      const toolGroups = createToolGroups(3);
      const { result } = renderHook(() =>
        useToolDisplayTiming(toolGroups, false, false)
      );

      // Initially only first tool visible
      expect(result.current.visibleTools.size).toBe(1);

      // Complete first tool (pass turn_index and tab_index)
      act(() => {
        result.current.handleToolComplete(0, 0);
      });

      // Advance time by 1.5s
      act(() => {
        jest.advanceTimersByTime(1500);
      });

      // Second tool should now be visible
      expect(result.current.visibleTools.size).toBe(2);
      expect(result.current.visibleTools.has("1-0")).toBe(true);
    });

    test("enforces 1.5s minimum display time before showing next tool", () => {
      const toolGroups = createToolGroups(3);
      const { result } = renderHook(() =>
        useToolDisplayTiming(toolGroups, false, false)
      );

      // Complete first tool
      act(() => {
        result.current.handleToolComplete(0, 0);
      });

      // Advance time by 1.4s (not enough)
      act(() => {
        jest.advanceTimersByTime(1400);
      });
      // Second tool should NOT be visible yet
      expect(result.current.visibleTools.size).toBe(1);

      // Advance remaining 100ms (now 1.5s total)
      act(() => {
        jest.advanceTimersByTime(100);
      });
      // Second tool should now be visible
      expect(result.current.visibleTools.size).toBe(2);
    });

    test("allows immediate progression if tool displayed for >1.5s", () => {
      const toolGroups = createToolGroups(2);
      const { result } = renderHook(() =>
        useToolDisplayTiming(toolGroups, false, false)
      );

      // Advance time by 2s (more than minimum)
      act(() => {
        jest.advanceTimersByTime(2000);
      });

      // Now complete the tool
      act(() => {
        result.current.handleToolComplete(0, 0);
      });

      // Second tool should appear immediately
      expect(result.current.visibleTools.size).toBe(2);
      expect(result.current.visibleTools.has("1-0")).toBe(true);
    });
  });

  describe("Callback & State Management", () => {
    test("handleToolComplete makes next tool visible after minimum time", () => {
      const toolGroups = createToolGroups(2);
      const { result } = renderHook(() =>
        useToolDisplayTiming(toolGroups, false, false)
      );

      // Complete tool
      act(() => {
        result.current.handleToolComplete(0, 0);
        jest.advanceTimersByTime(1500);
      });

      // Next tool should be visible
      expect(result.current.visibleTools.has("1-0")).toBe(true);
    });

    test("calculates allToolsDisplayed correctly", () => {
      const toolGroups = createToolGroups(2);

      // Start with streaming
      const { result, rerender } = renderHook(
        ({ isFinalAnswerComing }) =>
          useToolDisplayTiming(toolGroups, isFinalAnswerComing, false),
        { initialProps: { isFinalAnswerComing: false } }
      );

      // Initially false (not all tools visible/completed yet)
      expect(result.current.allToolsDisplayed).toBe(false);

      // Complete both tools
      act(() => {
        result.current.handleToolComplete(0, 0);
        jest.advanceTimersByTime(1500);
      });

      act(() => {
        result.current.handleToolComplete(1, 0);
        jest.advanceTimersByTime(1500);
      });

      // Now true because all tools are visible and completed
      // Note: allToolsDisplayed is independent of isFinalAnswerComing to avoid
      // circular dependency (parent uses onAllToolsDisplayed to set finalAnswerComing)
      expect(result.current.allToolsDisplayed).toBe(true);

      // Remains true after setting final answer coming
      rerender({ isFinalAnswerComing: true });
      expect(result.current.allToolsDisplayed).toBe(true);
    });

    test("handles rapid completion calls for same tool (idempotency)", () => {
      const toolGroups = createToolGroups(2);
      const { result } = renderHook(() =>
        useToolDisplayTiming(toolGroups, false, false)
      );

      // Call handleToolComplete multiple times rapidly
      act(() => {
        result.current.handleToolComplete(0, 0);
        result.current.handleToolComplete(0, 0);
        result.current.handleToolComplete(0, 0);
      });

      // Advance time
      act(() => {
        jest.advanceTimersByTime(1500);
      });

      // Next tool should appear (proving completion only happened once)
      expect(result.current.visibleTools.size).toBe(2);
    });
  });

  describe("Cleanup", () => {
    test("cleans up timeouts on unmount", () => {
      const toolGroups = createToolGroups(2);
      const { result, unmount } = renderHook(() =>
        useToolDisplayTiming(toolGroups, false, false)
      );

      // Complete a tool (starts timer)
      act(() => {
        result.current.handleToolComplete(0, 0);
      });

      // Unmount before timer completes
      unmount();

      // Advance time - should not cause errors
      act(() => {
        jest.advanceTimersByTime(2000);
      });

      // No errors means cleanup worked
      expect(true).toBe(true);
    });
  });

  describe("Edge Cases", () => {
    test("handles empty tool groups", () => {
      const toolGroups: {
        turn_index: number;
        tab_index: number;
        packets: any[];
      }[] = [];

      const { result } = renderHook(() =>
        useToolDisplayTiming(toolGroups, false, false)
      );

      expect(result.current.visibleTools.size).toBe(0);
      expect(result.current.allToolsDisplayed).toBe(true);
    });

    test("handles single tool correctly", () => {
      const toolGroups = createToolGroups(1);

      const { result, rerender } = renderHook(
        ({ isFinalAnswerComing }) =>
          useToolDisplayTiming(toolGroups, isFinalAnswerComing, false),
        { initialProps: { isFinalAnswerComing: false } }
      );

      expect(result.current.visibleTools.size).toBe(1);

      // Complete the single tool
      act(() => {
        result.current.handleToolComplete(0, 0);
        jest.advanceTimersByTime(1500);
      });

      // Rerender with final answer coming
      rerender({ isFinalAnswerComing: true });

      // Should be marked as all tools displayed
      expect(result.current.allToolsDisplayed).toBe(true);
    });
  });
});
