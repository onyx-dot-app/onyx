import { renderHook } from "@testing-library/react";
import { useTimeRange } from "@/lib/usage/hooks";

describe("useTimeRange", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date(2026, 7, 4, 12));
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("defaults to exactly 30 calendar days", () => {
    const { result } = renderHook(() => useTimeRange());
    const [range] = result.current;

    expect(range.from.getFullYear()).toBe(2026);
    expect(range.from.getMonth()).toBe(6);
    expect(range.from.getDate()).toBe(6);
    expect(range.to.getFullYear()).toBe(2026);
    expect(range.to.getMonth()).toBe(7);
    expect(range.to.getDate()).toBe(4);
  });
});
