import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import { act, renderHook } from "@testing-library/react-native";

import { toast, useToasts } from "@/hooks/useToast";

describe("useToast store", () => {
  beforeEach(() => {
    act(() => toast.clearAll());
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  it("adds a toast with its level, message, and dismissible default", () => {
    const { result } = renderHook(() => useToasts());
    act(() => {
      toast.error("boom");
    });
    expect(result.current).toHaveLength(1);
    expect(result.current[0]).toMatchObject({
      level: "error",
      message: "boom",
      dismissible: true,
    });
  });

  it("dismiss removes a toast by id", () => {
    const { result } = renderHook(() => useToasts());
    let id = "";
    act(() => {
      id = toast.warning("careful");
    });
    expect(result.current).toHaveLength(1);
    act(() => {
      toast.dismiss(id);
    });
    expect(result.current).toHaveLength(0);
  });

  it("auto-dismisses after the duration", () => {
    jest.useFakeTimers();
    const { result } = renderHook(() => useToasts());
    act(() => {
      toast.info("hi", { duration: 1000 });
    });
    expect(result.current).toHaveLength(1);
    act(() => {
      jest.advanceTimersByTime(1000);
    });
    expect(result.current).toHaveLength(0);
  });

  it("duration Infinity persists (no auto-dismiss)", () => {
    jest.useFakeTimers();
    const { result } = renderHook(() => useToasts());
    act(() => {
      toast.error("stay", { duration: Infinity });
    });
    act(() => {
      jest.advanceTimersByTime(100_000);
    });
    expect(result.current).toHaveLength(1);
  });

  it("clearAll empties the list", () => {
    const { result } = renderHook(() => useToasts());
    act(() => {
      toast.error("a");
      toast.error("b");
    });
    expect(result.current).toHaveLength(2);
    act(() => {
      toast.clearAll();
    });
    expect(result.current).toHaveLength(0);
  });
});
