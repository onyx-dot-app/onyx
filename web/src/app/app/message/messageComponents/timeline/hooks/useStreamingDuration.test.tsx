import { act, renderHook } from "@testing-library/react";
import { useStreamingDuration } from "@/app/app/message/messageComponents/timeline/hooks/useStreamingDuration";

afterEach(() => jest.useRealTimers());

test("time spent waiting for an approval does not count", () => {
  jest.useFakeTimers({ now: 1_000 });
  const { result, rerender } = renderHook(
    ({ paused }) => useStreamingDuration(true, 1_000, undefined, paused),
    { initialProps: { paused: false } }
  );

  act(() => jest.advanceTimersByTime(5_100));
  expect(result.current).toBe(5);

  rerender({ paused: true });
  act(() => jest.advanceTimersByTime(600_000));
  expect(result.current).toBe(5);

  rerender({ paused: false });
  act(() => jest.advanceTimersByTime(2_100));
  expect(result.current).toBe(7);
});
