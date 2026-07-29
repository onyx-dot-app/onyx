import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { act, renderHook } from "@testing-library/react-native";
import type { RefObject } from "react";
import type {
  LayoutChangeEvent,
  NativeScrollEvent,
  NativeSyntheticEvent,
} from "react-native";

import {
  useChatAutoScroll,
  type UseChatAutoScrollParams,
} from "@/hooks/useChatAutoScroll";

// Deferred requestAnimationFrame: callbacks queue by id and run only on flushRaf(). This preserves
// the real schedule→fire gap so a test can interleave an onScroll (unpin) between a content-change
// rerender and the follow scroll — the window the fire-time-staleness race lives in. cancel truly
// drops a pending callback, so the coalescing path is exercised too.
let rafCbs: Map<number, FrameRequestCallback>;
let nextRafId: number;

function flushRaf() {
  const entries = [...rafCbs.entries()];
  rafCbs.clear();
  entries.forEach(([, cb]) => cb(0));
}

beforeEach(() => {
  rafCbs = new Map();
  nextRafId = 1;
  jest
    .spyOn(global, "requestAnimationFrame")
    .mockImplementation((cb: FrameRequestCallback) => {
      const id = nextRafId++;
      rafCbs.set(id, cb);
      return id as unknown as number;
    });
  jest
    .spyOn(global, "cancelAnimationFrame")
    .mockImplementation((id: number | null | undefined) => {
      if (id != null) rafCbs.delete(id);
    });
});

function scrollEvent(
  offsetY: number,
  contentHeight = 1000,
  viewportHeight = 600,
): NativeSyntheticEvent<NativeScrollEvent> {
  return {
    nativeEvent: {
      contentOffset: { y: offsetY },
      contentSize: { height: contentHeight },
      layoutMeasurement: { height: viewportHeight },
    },
  } as unknown as NativeSyntheticEvent<NativeScrollEvent>;
}

function layoutEvent(height: number): LayoutChangeEvent {
  return {
    nativeEvent: { layout: { height } },
  } as unknown as LayoutChangeEvent;
}

function setup(
  initial: UseChatAutoScrollParams = { enabled: true, contentSignature: "0" },
) {
  const scrollToEnd = jest.fn();
  const listRef = { current: { scrollToEnd } } as RefObject<{
    scrollToEnd: (params?: { animated?: boolean }) => void;
  } | null>;
  const view = renderHook(
    (props: UseChatAutoScrollParams) => useChatAutoScroll(listRef, props),
    { initialProps: initial },
  );
  return { ...view, scrollToEnd };
}

describe("useChatAutoScroll", () => {
  it("scrolls to the bottom once on load", () => {
    const { result, scrollToEnd } = setup();
    act(() => {
      result.current.onLoad();
      result.current.onLoad();
    });
    expect(scrollToEnd).toHaveBeenCalledTimes(1);
    expect(scrollToEnd).toHaveBeenCalledWith({ animated: false });
  });

  it("follows content growth while parked at the bottom", () => {
    const { rerender, scrollToEnd } = setup();
    scrollToEnd.mockClear();
    act(() => rerender({ enabled: true, contentSignature: "1" }));
    act(() => flushRaf());
    expect(scrollToEnd).toHaveBeenCalledWith({ animated: false });
  });

  // The core fix: a scroll-up that lands in the frame gap between a flush scheduling the follow and
  // that follow firing must NOT be yanked back. (Regression guard for the reintroduced race.)
  it("does not follow if the user scrolls up between the flush and the deferred scroll", () => {
    const { result, rerender, scrollToEnd } = setup();
    act(() => result.current.onScroll(scrollEvent(400))); // parked at bottom
    scrollToEnd.mockClear();

    act(() => rerender({ enabled: true, contentSignature: "1" })); // schedules the follow rAF
    act(() => result.current.onScroll(scrollEvent(200))); // user drags up in the gap → unpin
    act(() => flushRaf()); // rAF fires — must re-check the pin and bail

    expect(scrollToEnd).not.toHaveBeenCalled();
  });

  it("stops following after the user scrolls up, and resumes at the bottom", () => {
    const { result, rerender, scrollToEnd } = setup();
    act(() => result.current.onScroll(scrollEvent(200))); // unpin
    expect(result.current.showScrollButton).toBe(true);

    scrollToEnd.mockClear();
    act(() => rerender({ enabled: true, contentSignature: "1" }));
    act(() => flushRaf());
    expect(scrollToEnd).not.toHaveBeenCalled();

    act(() => result.current.onScroll(scrollEvent(360))); // back within the 48px band → re-pin
    expect(result.current.showScrollButton).toBe(false);
    act(() => rerender({ enabled: true, contentSignature: "2" }));
    act(() => flushRaf());
    expect(scrollToEnd).toHaveBeenCalledWith({ animated: false });
  });

  // Absolute-distance pin, not per-event direction: the band-crossing step here is only 4px, which a
  // direction check (unpin on a >4px up-move) would miss — so it stays pinned there — while the
  // absolute pin unpins. This is the case that actually distinguishes the two.
  it("unpins when a small step crosses the band (a direction epsilon would miss it)", () => {
    const { result } = setup();
    act(() => result.current.onScroll(scrollEvent(400))); // at bottom, pinned
    act(() => result.current.onScroll(scrollEvent(354))); // 46px up → still within the band
    expect(result.current.showScrollButton).toBe(false);
    act(() => result.current.onScroll(scrollEvent(350))); // +4px → 50px, just past the band
    expect(result.current.showScrollButton).toBe(true);
  });

  it("never follows when auto-scroll is disabled", () => {
    const { rerender, scrollToEnd } = setup({
      enabled: false,
      contentSignature: "0",
    });
    scrollToEnd.mockClear();
    act(() => rerender({ enabled: false, contentSignature: "1" }));
    act(() => flushRaf());
    expect(scrollToEnd).not.toHaveBeenCalled();
  });

  it("coalesces rapid flushes into a single scroll", () => {
    const { rerender, scrollToEnd } = setup();
    scrollToEnd.mockClear();
    act(() => rerender({ enabled: true, contentSignature: "1" }));
    act(() => rerender({ enabled: true, contentSignature: "2" }));
    act(() => rerender({ enabled: true, contentSignature: "3" }));
    act(() => flushRaf());
    expect(scrollToEnd).toHaveBeenCalledTimes(1);
  });

  // The reported gap: with auto-scroll off, content growing past the viewport must reveal the button
  // even though the user never scrolled (content growth fires no onScroll). onContentSizeChange does.
  it("reveals the jump button when content grows to overflow while not following", () => {
    const { result } = setup({ enabled: false, contentSignature: "0" });
    act(() => result.current.onLoad()); // marks the initial scroll done
    act(() => result.current.onLayout(layoutEvent(600))); // viewport known
    act(() => result.current.onContentSizeChange(0, 500)); // still fits → hidden
    expect(result.current.showScrollButton).toBe(false);
    act(() => result.current.onContentSizeChange(0, 1000)); // overflows at offset 0 → shown
    expect(result.current.showScrollButton).toBe(true);
  });

  it("does not flash the button on content growth that still fits the viewport", () => {
    const { result } = setup({ enabled: false, contentSignature: "0" });
    act(() => result.current.onLoad());
    act(() => result.current.onLayout(layoutEvent(600)));
    act(() => result.current.onContentSizeChange(0, 400)); // fits
    expect(result.current.showScrollButton).toBe(false);
  });

  it("leaves the button to the follow loop while pinned+enabled (content-size change is a no-op)", () => {
    const { result } = setup({ enabled: true, contentSignature: "0" });
    act(() => result.current.onLoad());
    act(() => result.current.onLayout(layoutEvent(600)));
    act(() => result.current.onContentSizeChange(0, 1000)); // following → button untouched
    expect(result.current.showScrollButton).toBe(false);
  });

  it("ignores content-size changes before the initial scroll or before layout", () => {
    const { result } = setup({ enabled: false, contentSignature: "0" });
    act(() => result.current.onContentSizeChange(0, 1000)); // no onLoad / onLayout yet
    expect(result.current.showScrollButton).toBe(false);
  });

  // A viewport resize (keyboard, rotation, split-screen) changes the bottom distance but fires no
  // scroll/content-size event, so onLayout must recompute the button, not just capture the height.
  it("refreshes the jump button on a viewport resize while not following", () => {
    const { result } = setup({ enabled: false, contentSignature: "0" });
    act(() => result.current.onLoad());
    act(() => result.current.onLayout(layoutEvent(600)));
    act(() => result.current.onContentSizeChange(0, 640)); // 40px over → within band → hidden
    expect(result.current.showScrollButton).toBe(false);
    act(() => result.current.onLayout(layoutEvent(400))); // shrinks (keyboard) → 240px below → shown
    expect(result.current.showScrollButton).toBe(true);
    act(() => result.current.onLayout(layoutEvent(600))); // restored → back within band → hidden
    expect(result.current.showScrollButton).toBe(false);
  });

  it("scrollToBottom re-pins, jumps animated, and keeps the button hidden through the settle", () => {
    const { result, rerender, scrollToEnd } = setup();
    act(() => result.current.onScroll(scrollEvent(200))); // unpin, button shows
    expect(result.current.showScrollButton).toBe(true);

    scrollToEnd.mockClear();
    act(() => result.current.scrollToBottom());
    expect(scrollToEnd).toHaveBeenCalledWith({ animated: true });
    expect(result.current.showScrollButton).toBe(false);

    // mid-animation scroll frames (still far from bottom) must NOT re-show the button
    act(() => result.current.onScroll(scrollEvent(200)));
    expect(result.current.showScrollButton).toBe(false);
    // arriving at the bottom clears the guard, and following resumes on the next flush
    act(() => result.current.onScroll(scrollEvent(400)));
    scrollToEnd.mockClear();
    act(() => rerender({ enabled: true, contentSignature: "1" }));
    act(() => flushRaf());
    expect(scrollToEnd).toHaveBeenCalledWith({ animated: false });
  });

  // Regression guard: a drag started during the jump's settle must unpin, not be swallowed and then
  // re-followed by the next streaming flush.
  it("releases the jump guard when the user grabs the list mid-settle", () => {
    const { result, rerender, scrollToEnd } = setup();
    act(() => result.current.onScroll(scrollEvent(200))); // scrolled up
    act(() => result.current.scrollToBottom()); // jump: guard on, pinned, button hidden
    expect(result.current.showScrollButton).toBe(false);

    act(() => result.current.onScrollBeginDrag()); // user grabs the list
    act(() => result.current.onScroll(scrollEvent(200))); // drag up now honored → unpin
    expect(result.current.showScrollButton).toBe(true);

    scrollToEnd.mockClear();
    act(() => rerender({ enabled: true, contentSignature: "1" })); // a flush must NOT re-follow
    act(() => flushRaf());
    expect(scrollToEnd).not.toHaveBeenCalled();
  });

  // Re-enabling auto-scroll while at the bottom should catch up to the latest (and hide the button),
  // not blindly hide a button that reflects real content grown below while auto-scroll was off.
  it("catches up to the bottom when auto-scroll is re-enabled while pinned", () => {
    const { result, rerender, scrollToEnd } = setup({
      enabled: false,
      contentSignature: "0",
    });
    act(() => result.current.onLoad());
    act(() => result.current.onLayout(layoutEvent(600)));
    act(() => result.current.onScroll(scrollEvent(400))); // at bottom → pinned
    act(() => result.current.onContentSizeChange(0, 2000)); // grew below → button shows
    expect(result.current.showScrollButton).toBe(true);

    scrollToEnd.mockClear();
    act(() => rerender({ enabled: true, contentSignature: "0" })); // re-enable, no content change
    expect(scrollToEnd).toHaveBeenCalledWith({ animated: true });
    expect(result.current.showScrollButton).toBe(false);
  });

  it("does not catch up on re-enable when the user is scrolled up", () => {
    const { result, rerender, scrollToEnd } = setup({
      enabled: false,
      contentSignature: "0",
    });
    act(() => result.current.onScroll(scrollEvent(200))); // scrolled up → not pinned
    scrollToEnd.mockClear();
    act(() => rerender({ enabled: true, contentSignature: "0" }));
    expect(scrollToEnd).not.toHaveBeenCalled();
    expect(result.current.showScrollButton).toBe(true);
  });

  it("exposes anchoring-only MVCP (no autoscroll threshold that would fight the manual follow)", () => {
    const { result } = setup();
    expect(result.current.maintainVisibleContentPosition).toEqual({});
    expect(
      "autoscrollToBottomThreshold" in
        result.current.maintainVisibleContentPosition,
    ).toBe(false);
  });
});
