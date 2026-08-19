/**
 * Regression coverage for visibility-gated polling: hidden tabs must not
 * tick, and returning to visibility runs a single catch-up tick when a full
 * interval has elapsed.
 */
import { act, renderHook } from "@testing-library/react";
import { setDocumentVisibility } from "@tests/setup/test-utils";
import { useVisibilityGatedInterval } from "@/hooks/useVisibilityGatedInterval";

describe("useVisibilityGatedInterval", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    setDocumentVisibility(true);
  });

  afterEach(() => {
    jest.useRealTimers();
    setDocumentVisibility(true);
  });

  test("ticks on the interval while visible", () => {
    const callback = jest.fn();
    renderHook(() => useVisibilityGatedInterval(callback, 1000));

    act(() => {
      jest.advanceTimersByTime(3000);
    });
    expect(callback).toHaveBeenCalledTimes(3);
  });

  test("skips ticks while hidden", () => {
    const callback = jest.fn();
    renderHook(() => useVisibilityGatedInterval(callback, 1000));

    setDocumentVisibility(false);
    act(() => {
      jest.advanceTimersByTime(10000);
    });
    expect(callback).not.toHaveBeenCalled();
  });

  test("runs one catch-up tick when an overdue tab becomes visible", () => {
    const callback = jest.fn();
    renderHook(() => useVisibilityGatedInterval(callback, 1000));

    setDocumentVisibility(false);
    act(() => {
      jest.advanceTimersByTime(5000);
    });
    expect(callback).not.toHaveBeenCalled();

    act(() => {
      setDocumentVisibility(true);
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(callback).toHaveBeenCalledTimes(1);
  });

  test("does not catch up when no full interval has elapsed", () => {
    const callback = jest.fn();
    renderHook(() => useVisibilityGatedInterval(callback, 60000));

    setDocumentVisibility(false);
    act(() => {
      jest.advanceTimersByTime(1000);
    });
    act(() => {
      setDocumentVisibility(true);
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(callback).not.toHaveBeenCalled();
  });

  test("does nothing when interval is null", () => {
    const callback = jest.fn();
    renderHook(() => useVisibilityGatedInterval(callback, null));

    act(() => {
      jest.advanceTimersByTime(60000);
    });
    expect(callback).not.toHaveBeenCalled();
  });

  test("stops ticking after unmount", () => {
    const callback = jest.fn();
    const { unmount } = renderHook(() =>
      useVisibilityGatedInterval(callback, 1000)
    );
    unmount();

    act(() => {
      jest.advanceTimersByTime(5000);
    });
    expect(callback).not.toHaveBeenCalled();
  });
});
