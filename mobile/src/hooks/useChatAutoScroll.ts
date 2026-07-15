// Web-parity auto-scroll for the chat message list (see web ChatScrollContainer).
//
// While the assistant streams, the list follows the latest turn only while the user is parked at the
// bottom; scrolling up stops the follow (so earlier content can be read) and returning to the bottom
// resumes it. The `enabled` flag turns following off entirely.
//
// The follow is driven MANUALLY (scrollToEnd per content change while pinned), NOT via FlashList's
// maintainVisibleContentPosition.autoscrollToBottomThreshold: its built-in follow arms an internal
// flag from a wider band a frame before a prop change lands, and dropping the threshold can't cancel
// it, so a slow scroll-up gets snapped back. MVCP stays on for anchoring only (no threshold set), so
// the read position holds if content above the viewport reflows.
//
// The pin is ABSOLUTE distance to the bottom (isWithinBottomBand), not scroll direction: the follow
// always lands at the bottom, so any scroll event reporting a position beyond the band is the user
// pulling away, and content growth fires no scroll event so it can't move the pin.
import { RefObject, useCallback, useEffect, useRef, useState } from "react";
import { NativeScrollEvent, NativeSyntheticEvent } from "react-native";

import { isWithinBottomBand } from "@/chat/autoScroll";

// The subset of the FlashList ref this hook drives — decoupled from the list item type.
interface ScrollableRef {
  scrollToEnd: (params?: { animated?: boolean }) => void;
}

// Anchoring-only MVCP: enabled (its `disabled` defaults to false) but with no autoscroll threshold,
// so FlashList never auto-follows — we do. Stable identity avoids re-initializing MVCP per render.
export const ANCHOR_ONLY_MVCP = {} as const;

// Fallback window for ignoring the animated jump's own scroll events, in case it never reports
// reaching the bottom (e.g. a no-op jump when already there). Web uses 600ms.
const AUTO_SCROLL_SETTLE_MS = 600;

export interface UseChatAutoScrollParams {
  // Master toggle (app setting). When off, the list never auto-follows; the jump button still works.
  enabled: boolean;
  // Changes whenever the rendered content grows (new turn or a streaming flush). Drives the follow.
  contentSignature: string;
}

export interface ChatAutoScroll {
  onLoad: () => void;
  onScroll: (event: NativeSyntheticEvent<NativeScrollEvent>) => void;
  onScrollBeginDrag: () => void;
  scrollToBottom: () => void;
  showScrollButton: boolean;
  maintainVisibleContentPosition: typeof ANCHOR_ONLY_MVCP;
}

export function useChatAutoScroll(
  listRef: RefObject<ScrollableRef | null>,
  { enabled, contentSignature }: UseChatAutoScrollParams,
): ChatAutoScroll {
  const didInitialScroll = useRef(false);
  // pinnedRef = "follow the bottom". A ref (not state): nothing rendered depends on it, so flipping
  // it must not re-render; it's read fresh in onScroll and at the follow rAF's fire time.
  const pinnedRef = useRef(true);
  const hasOverflowedRef = useRef(false);
  // True while our own animated jump is running, so its scroll events don't flicker the button or
  // unpin the list before it reaches the bottom. Cleared when it reaches the bottom, when the user
  // grabs the list (onScrollBeginDrag), or by a fallback timer.
  const isAutoScrollingRef = useRef(false);
  const settleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevSignatureRef = useRef(contentSignature);
  const rafRef = useRef<number | null>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);

  // Land on the newest turn when a chat opens (web's session-load scroll-to-bottom); no-op for short
  // chats. Reset per session by keying the list on sessionId (see MessageList / ChatSurface).
  const onLoad = useCallback(() => {
    if (didInitialScroll.current) return;
    didInitialScroll.current = true;
    listRef.current?.scrollToEnd({ animated: false });
  }, [listRef]);

  const onScroll = useCallback(
    (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      const { contentOffset, contentSize, layoutMeasurement } =
        event.nativeEvent;
      const metrics = {
        offsetY: contentOffset.y,
        contentHeight: contentSize.height,
        viewportHeight: layoutMeasurement.height,
      };
      const atBottom = isWithinBottomBand(metrics);

      // Ignore the animated jump's own scroll stream until it lands, so it doesn't unpin/flicker.
      // A user drag is exempt (see onScrollBeginDrag) so a mid-jump grab isn't swallowed.
      if (isAutoScrollingRef.current) {
        if (atBottom) isAutoScrollingRef.current = false;
        return;
      }

      if (metrics.contentHeight > metrics.viewportHeight) {
        hasOverflowedRef.current = true;
      }
      pinnedRef.current = atBottom;
      setShowScrollButton(!atBottom);
    },
    [],
  );

  // The user grabbed the list: a programmatic jump never fires this, so it cleanly ends the jump
  // guard. Without it a drag started during the settle is swallowed and the next flush re-follows.
  const onScrollBeginDrag = useCallback(() => {
    isAutoScrollingRef.current = false;
  }, []);

  // Explicit jump: re-pin so streaming resumes following from the bottom.
  const scrollToBottom = useCallback(() => {
    pinnedRef.current = true;
    setShowScrollButton(false);
    isAutoScrollingRef.current = true;
    listRef.current?.scrollToEnd({ animated: true });
    if (settleTimerRef.current) clearTimeout(settleTimerRef.current);
    settleTimerRef.current = setTimeout(() => {
      isAutoScrollingRef.current = false;
      settleTimerRef.current = null;
    }, AUTO_SCROLL_SETTLE_MS);
  }, [listRef]);

  // Follow on content growth. The rAF defers one frame so FlashList has measured the appended content
  // before we scroll to its end (FlashList v2 has no onContentSizeChange), and coalesces rapid flushes
  // via the cleanup cancel. The pin is re-checked when the frame FIRES: an onScroll unpin in the gap
  // can't re-run this effect (pinnedRef is a ref), so the schedule-time check is already stale.
  useEffect(() => {
    const contentChanged = prevSignatureRef.current !== contentSignature;
    prevSignatureRef.current = contentSignature;
    if (!contentChanged) return;

    if (enabled && pinnedRef.current) {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        if (!pinnedRef.current) return; // user scrolled up between schedule and fire → don't yank
        listRef.current?.scrollToEnd({ animated: false });
      });
      return () => {
        if (rafRef.current != null) {
          cancelAnimationFrame(rafRef.current);
          rafRef.current = null;
        }
      };
    }

    // Not following: content grew below the viewport, which fires no scroll event, so onScroll can't
    // reveal the jump button. Do it here — guarded on known overflow so a short chat never flashes it.
    if (hasOverflowedRef.current) setShowScrollButton(true);
  }, [contentSignature, enabled, listRef]);

  useEffect(
    () => () => {
      if (settleTimerRef.current) clearTimeout(settleTimerRef.current);
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    },
    [],
  );

  return {
    onLoad,
    onScroll,
    onScrollBeginDrag,
    scrollToBottom,
    showScrollButton,
    maintainVisibleContentPosition: ANCHOR_ONLY_MVCP,
  };
}
