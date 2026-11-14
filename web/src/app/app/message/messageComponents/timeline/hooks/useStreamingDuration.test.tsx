import { act, renderHook } from "@testing-library/react";
import {
  type ApprovalWait,
  useStreamingDuration,
} from "@/app/app/message/messageComponents/timeline/hooks/useStreamingDuration";

afterEach(() => jest.useRealTimers());

test("time spent waiting for an approval does not count", () => {
  jest.useFakeTimers({ now: 1_000 });
  const working: ApprovalWait = { excludedMs: 0, since: null };
  const { result, rerender } = renderHook(
    ({ wait }: { wait: ApprovalWait }) =>
      useStreamingDuration(true, 1_000, undefined, wait),
    { initialProps: { wait: working } }
  );

  act(() => jest.advanceTimersByTime(5_100));
  expect(result.current).toBe(5);

  rerender({ wait: { excludedMs: 0, since: Date.now() } });
  act(() => jest.advanceTimersByTime(600_000));
  expect(result.current).toBe(5);

  rerender({ wait: { excludedMs: 600_000, since: null } });
  act(() => jest.advanceTimersByTime(2_100));
  expect(result.current).toBe(7);
});

test("a timer that mounts during a wait shows the time before it", () => {
  jest.useFakeTimers({ now: 61_000 });
  const { result } = renderHook(() =>
    useStreamingDuration(true, 1_000, undefined, {
      excludedMs: 10_000,
      since: 31_000,
    })
  );

  expect(result.current).toBe(20);
});
