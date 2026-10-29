import { act, renderHook } from "@testing-library/react";
import { useTypewriter } from "@/hooks/useTypewriter";

test("restored text is visible before animation advances the live suffix", () => {
  jest.useFakeTimers();
  const { result, rerender, unmount } = renderHook(
    ({ text, restored }) => useTypewriter(text, true, false, restored),
    { initialProps: { text: "Saved text. A long live suffix.", restored: 11 } }
  );
  try {
    expect(result.current.displayed).toBe("Saved text.");
    act(() => jest.advanceTimersByTime(17));
    expect(result.current.displayed.length).toBeGreaterThan(11);
    expect(result.current.displayed.length).toBeLessThan(30);
    rerender({
      text: "Saved text. A long live suffix.",
      restored: "Saved text. A long live".length,
    });
    expect(result.current.displayed).toBe("Saved text. A long live");
  } finally {
    unmount();
    jest.useRealTimers();
  }
});

test("small live batches do not drain immediately between arrivals", () => {
  jest.useFakeTimers();
  const { result, rerender, unmount } = renderHook(
    ({ text }) => useTypewriter(text, true),
    { initialProps: { text: "" } }
  );
  try {
    let text = "";
    for (let batch = 0; batch < 3; batch++) {
      const before = result.current.displayed.length;
      text += "A small batch of text. ";
      rerender({ text });
      act(() => jest.advanceTimersByTime(150));
      expect(result.current.displayed.length).toBeGreaterThan(before);
      expect(result.current.displayed.length).toBeLessThan(text.length);
      act(() => jest.advanceTimersByTime(50));
    }
  } finally {
    unmount();
    jest.useRealTimers();
  }
});

test("reveal speed does not depend on display refresh rate", () => {
  jest.useFakeTimers();
  const lengths: number[] = [];
  try {
    for (const frameMs of [16, 8]) {
      jest
        .spyOn(window, "requestAnimationFrame")
        .mockImplementation((callback) =>
          window.setTimeout(() => callback(performance.now()), frameMs)
        );
      jest
        .spyOn(window, "cancelAnimationFrame")
        .mockImplementation(window.clearTimeout);
      const { result, unmount } = renderHook(() =>
        useTypewriter("x".repeat(200), true)
      );
      act(() => jest.advanceTimersByTime(320));
      lengths.push(result.current.displayed.length);
      unmount();
      jest.restoreAllMocks();
    }
    expect(Math.abs(lengths[0]! - lengths[1]!)).toBeLessThanOrEqual(2);
  } finally {
    jest.restoreAllMocks();
    jest.useRealTimers();
  }
});

test("completion drains the tail and releases the animation loop", () => {
  jest.useFakeTimers();
  const text = "x".repeat(200);
  const { result, rerender, unmount } = renderHook(
    ({ finished }) => useTypewriter(text, true, finished),
    { initialProps: { finished: false } }
  );
  try {
    act(() => jest.advanceTimersByTime(100));
    expect(result.current.displayed.length).toBeLessThan(text.length);
    rerender({ finished: true });
    act(() => jest.advanceTimersByTime(32));
    expect(result.current.isDraining).toBe(true);
    act(() => jest.advanceTimersByTime(600));
    expect(result.current.displayed).toBe(text);
    expect(result.current.isDraining).toBe(false);
    expect(jest.getTimerCount()).toBe(0);
  } finally {
    unmount();
    jest.useRealTimers();
  }
});
