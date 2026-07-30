import { describe, expect, it } from "@jest/globals";
import { act, renderHook } from "@testing-library/react-native";

import { TurnGroup } from "@/chat/timeline/transformers";
import { useTimelineExpansion } from "@/hooks/timeline/useTimelineExpansion";

import { makeStep, makeTurn } from "./testHelpers";

// Only handleToggle can expand (and it sets userHasToggled), so auto-collapse (which only sets
// isExpanded=false) is a no-op from the collapsed default — its observable job is to not fight a
// user who manually expanded.

const parallelTurn = makeTurn(0, [makeStep(0, 0, []), makeStep(0, 1, [])]);
const parallelTurnB = makeTurn(1, [makeStep(1, 0, []), makeStep(1, 1, [])]);

describe("useTimelineExpansion", () => {
  it("starts collapsed and toggles on user action", () => {
    const { result } = renderHook(() =>
      useTimelineExpansion(false, undefined, false),
    );
    expect(result.current.isExpanded).toBe(false);

    act(() => result.current.handleToggle());
    expect(result.current.isExpanded).toBe(true);

    act(() => result.current.handleToggle());
    expect(result.current.isExpanded).toBe(false);
  });

  it("stays collapsed through stop / display when untouched", () => {
    const { result, rerender } = renderHook(
      ({ stop, display }: { stop: boolean; display: boolean }) =>
        useTimelineExpansion(stop, undefined, display),
      { initialProps: { stop: false, display: false } },
    );
    expect(result.current.isExpanded).toBe(false);
    rerender({ stop: true, display: false });
    expect(result.current.isExpanded).toBe(false);
    rerender({ stop: true, display: true });
    expect(result.current.isExpanded).toBe(false);
  });

  it("respects user intent — a manual expand survives the stop packet", () => {
    const { result, rerender } = renderHook(
      ({ stop }: { stop: boolean }) =>
        useTimelineExpansion(stop, undefined, false),
      { initialProps: { stop: false } },
    );
    act(() => result.current.handleToggle());
    expect(result.current.isExpanded).toBe(true);
    rerender({ stop: true });
    expect(result.current.isExpanded).toBe(true);
  });

  it("respects user intent — a manual expand survives the final message starting", () => {
    const { result, rerender } = renderHook(
      ({ display }: { display: boolean }) =>
        useTimelineExpansion(false, undefined, display),
      { initialProps: { display: false } },
    );
    act(() => result.current.handleToggle());
    expect(result.current.isExpanded).toBe(true);
    rerender({ display: true });
    expect(result.current.isExpanded).toBe(true);
  });

  it("selects the first tab of a parallel turn group and re-syncs when it changes", () => {
    const { result, rerender } = renderHook(
      ({ turn }: { turn: TurnGroup | undefined }) =>
        useTimelineExpansion(false, turn, false),
      { initialProps: { turn: undefined as TurnGroup | undefined } },
    );
    expect(result.current.parallelActiveTab).toBe("");

    rerender({ turn: parallelTurn });
    expect(result.current.parallelActiveTab).toBe("0-0");

    rerender({ turn: parallelTurnB });
    expect(result.current.parallelActiveTab).toBe("1-0");
  });

  it("leaves a valid selected tab untouched when the same turn re-renders", () => {
    const { result, rerender } = renderHook(
      ({ turn }: { turn: TurnGroup | undefined }) =>
        useTimelineExpansion(false, turn, false),
      { initialProps: { turn: parallelTurn as TurnGroup | undefined } },
    );
    expect(result.current.parallelActiveTab).toBe("0-0");
    act(() => result.current.setParallelActiveTab("0-1"));
    expect(result.current.parallelActiveTab).toBe("0-1");
    rerender({ turn: parallelTurn });
    expect(result.current.parallelActiveTab).toBe("0-1");
  });
});
