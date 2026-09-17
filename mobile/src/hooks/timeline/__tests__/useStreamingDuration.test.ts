import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import { act, renderHook } from "@testing-library/react-native";

import { useStreamingDuration } from "@/hooks/timeline/useStreamingDuration";

// Modern fake timers mock Date.now() too, so elapsed advances with the fake clock as the poll fires.
describe("useStreamingDuration", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  it("starts at 0 and ticks once per whole second", () => {
    const start = Date.now();
    const { result } = renderHook(() => useStreamingDuration(true, start));
    expect(result.current).toBe(0);

    act(() => jest.advanceTimersByTime(1000));
    expect(result.current).toBe(1);

    act(() => jest.advanceTimersByTime(2000));
    expect(result.current).toBe(3);
  });

  it("does not re-tick within the same second", () => {
    const start = Date.now();
    const { result } = renderHook(() => useStreamingDuration(true, start));
    act(() => jest.advanceTimersByTime(500));
    expect(result.current).toBe(0);
    act(() => jest.advanceTimersByTime(499));
    expect(result.current).toBe(0);
    act(() => jest.advanceTimersByTime(1));
    expect(result.current).toBe(1);
  });

  it("freezes at the backend duration when provided", () => {
    const start = Date.now();
    const { result } = renderHook(() => useStreamingDuration(true, start, 42));
    expect(result.current).toBe(42);
    act(() => jest.advanceTimersByTime(5000));
    expect(result.current).toBe(42);
  });

  it("stops advancing when streaming ends but keeps the last value", () => {
    const start = Date.now();
    const { result, rerender } = renderHook(
      ({ streaming }: { streaming: boolean }) =>
        useStreamingDuration(streaming, start),
      { initialProps: { streaming: true } },
    );
    act(() => jest.advanceTimersByTime(2000));
    expect(result.current).toBe(2);

    rerender({ streaming: false });
    act(() => jest.advanceTimersByTime(5000));
    // Preserved, not reset, because startTime is still defined.
    expect(result.current).toBe(2);
  });

  it("resets to 0 when there is no start time", () => {
    const { result } = renderHook(() => useStreamingDuration(true, undefined));
    expect(result.current).toBe(0);
    act(() => jest.advanceTimersByTime(3000));
    expect(result.current).toBe(0);
  });

  it("does not carry the prior stream's duration to a new startTime", () => {
    const start = Date.now();
    const { result, rerender } = renderHook(
      ({ s, streaming }: { s: number; streaming: boolean }) =>
        useStreamingDuration(streaming, s),
      { initialProps: { s: start, streaming: true } },
    );
    act(() => jest.advanceTimersByTime(3000));
    expect(result.current).toBe(3);

    // New stream while the timer is off: the effect won't reconcile, so the render-phase reset is
    // what prevents the old 3s from leaking into the new stream.
    rerender({ s: Date.now() + 500, streaming: false });
    expect(result.current).toBe(0);
  });
});
