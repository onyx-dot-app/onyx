"use client";

import React, { useEffect, useLayoutEffect, useRef, useCallback } from "react";
import { useCurrentChatState } from "@/app/app/stores/useChatSessionStore";
import { useScrollContainer } from "@/lib/chatScroll/components/ScrollContainerContext";
import { getChatScrollMemory } from "@/lib/chatScroll/scrollMemory";

// Small offset from the top of the scroll viewport where the anchor should appear.
// The header is outside the scroll container, so when scrolled to the bottom
// during the push-up effect, we only need minimal padding.
const ANCHOR_TOP_OFFSET_PX = 16;

// Duration of smooth scroll animation (browser default is ~400-500ms, we add buffer)
const SMOOTH_SCROLL_DURATION_MS = 600;

export interface DynamicBottomSpacerProps {
  /** DOM id of the anchor message's row (the new user message). */
  anchorRowId?: string;
}

/**
 * DynamicBottomSpacer creates a "fresh chat" effect by filling the space
 * below messages to push content up when a new round starts.
 * Uses ResizeObserver to efficiently detect content changes instead of polling.
 */
const DynamicBottomSpacer = React.memo(
  ({ anchorRowId }: DynamicBottomSpacerProps) => {
    const spacerRef = useRef<HTMLDivElement>(null);
    const chatState = useCurrentChatState();
    const isStreaming = chatState === "streaming" || chatState === "loading";
    // A send from this page passes through "loading". A run the page resumes
    // (a reload, or a chat it opens mid-run) starts at "streaming" and is not
    // a new turn, so it must not push the history up.
    const sentHereRef = useRef(false);

    // Get scroll container refs from context (provided by ChatScrollContainer)
    const {
      scrollContainerRef,
      contentWrapperRef,
      spacerHeightRef,
      sessionId,
      spaceRestoreRef,
    } = useScrollContainer();

    // Track state with refs to avoid re-renders
    const isActiveRef = useRef(false);
    const prevAnchorRowIdRef = useRef<string | undefined>(undefined);
    const wasStreamingRef = useRef(false);
    const resizeObserverRef = useRef<ResizeObserver | null>(null);

    /**
     * Set spacer height directly on DOM (no re-renders)
     */
    const setHeight = useCallback(
      (height: number) => {
        const h = Math.max(0, Math.round(height));
        spacerHeightRef.current = h;
        if (spacerRef.current) {
          spacerRef.current.style.height = `${h}px`;
        }
      },
      [spacerHeightRef]
    );

    /**
     * Get the scroll container element from context ref
     */
    const getScrollContainer = useCallback(() => {
      return scrollContainerRef.current;
    }, [scrollContainerRef]);

    /**
     * Spacer height that stops the scroll with the anchor at the top offset.
     * Measured from the live layout, so content that changes size above or
     * below the anchor keeps the anchor in place.
     */
    const measureSpacerHeight = useCallback((): number | null => {
      if (!anchorRowId) return null;
      const anchor = document.getElementById(anchorRowId);
      const scrollContainer = getScrollContainer();
      const spacer = spacerRef.current;
      if (!anchor || !scrollContainer || !spacer) return null;

      // The spacer is the last content, so its top is where the messages
      // end. Unlike scrollHeight, it is exact when the chat is shorter than
      // the viewport.
      const containerTop = scrollContainer.getBoundingClientRect().top;
      const anchorTop = anchor.getBoundingClientRect().top - containerTop;
      const contentEnd = spacer.getBoundingClientRect().top - containerTop;

      return (
        anchorTop -
        ANCHOR_TOP_OFFSET_PX +
        scrollContainer.clientHeight -
        contentEnd
      );
    }, [anchorRowId, getScrollContainer]);

    /**
     * Stop observing and clean up
     */
    const stopObserving = useCallback(() => {
      if (resizeObserverRef.current) {
        resizeObserverRef.current.disconnect();
        resizeObserverRef.current = null;
      }
    }, []);

    /**
     * Re-fit the spacer to the current layout. It stays fitted for the whole
     * turn: a taller viewport or a shorter reply can need it again after it
     * reached 0.
     */
    const updateSpacerHeight = useCallback(() => {
      if (!isActiveRef.current) return;

      const height = measureSpacerHeight();
      if (height !== null) setHeight(height);
    }, [measureSpacerHeight, setHeight]);

    /**
     * Start observing content changes with ResizeObserver
     */
    const startObserving = useCallback(() => {
      const scrollContainer = getScrollContainer();
      if (!scrollContainer || resizeObserverRef.current) return;

      // Keep fitting after the stream ends: a reply's footer, late layout and
      // window resizes still change the fit.
      resizeObserverRef.current = new ResizeObserver(updateSpacerHeight);

      // The viewport too: its height is part of the fit.
      resizeObserverRef.current.observe(scrollContainer);
      if (contentWrapperRef.current) {
        resizeObserverRef.current.observe(contentWrapperRef.current);
      }
    }, [getScrollContainer, updateSpacerHeight, contentWrapperRef]);

    /**
     * Activate the spacer - calculate initial height and scroll to bottom
     */
    const activate = useCallback(() => {
      stopObserving();
      isActiveRef.current = false;

      const scrollContainer = getScrollContainer();
      const spacerHeight = measureSpacerHeight();
      if (!scrollContainer || spacerHeight === null) return;

      isActiveRef.current = true;
      setHeight(spacerHeight);
      startObserving();
      if (sessionId && anchorRowId) {
        getChatScrollMemory(sessionId).spaceAnchorRowId = anchorRowId;
      }

      // No room needed: the anchor already reaches the top (a tall message),
      // and scrolling to the end would scroll past it.
      if (spacerHeight <= 0) return;

      // Tell ChatScrollContainer to not do instant auto-scroll during smooth scroll
      scrollContainer.dataset.smoothScrollActive = "true";

      // Scroll to bottom smoothly (after spacer height is applied)
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          scrollContainer.scrollTo({
            top: scrollContainer.scrollHeight - scrollContainer.clientHeight,
            behavior: "smooth",
          });

          // Clear the flag after smooth scroll completes and force
          // ChatScrollContainer to refresh scroll state (button visibility,
          // fades). The MutationObserver doesn't observe attribute changes,
          // so we dispatch a synthetic scroll event.
          setTimeout(() => {
            scrollContainer.dataset.smoothScrollActive = "false";
            scrollContainer.dispatchEvent(new Event("scroll"));
          }, SMOOTH_SCROLL_DURATION_MS);
        });
      });
    }, [
      sessionId,
      anchorRowId,
      measureSpacerHeight,
      setHeight,
      getScrollContainer,
      startObserving,
      stopObserving,
    ]);

    /**
     * Reopening a chat whose latest turn had space: fit the space again, with
     * no scroll. ChatScrollContainer runs the fit before it restores the
     * saved position, once the scroll element's ref is attached; this child
     * layout effect runs before that.
     */
    useLayoutEffect(() => {
      if (!sessionId || !anchorRowId || isActiveRef.current) return;
      if (getChatScrollMemory(sessionId).spaceAnchorRowId !== anchorRowId) {
        return;
      }
      const restore = () => {
        if (isActiveRef.current) return;
        const spacerHeight = measureSpacerHeight();
        if (spacerHeight === null) return;
        isActiveRef.current = true;
        setHeight(spacerHeight);
        startObserving();
      };
      spaceRestoreRef.current = restore;
      return () => {
        if (spaceRestoreRef.current === restore) spaceRestoreRef.current = null;
      };
    }, [
      sessionId,
      anchorRowId,
      measureSpacerHeight,
      setHeight,
      startObserving,
      spaceRestoreRef,
    ]);

    /**
     * Main effect: detect streaming start/stop and anchor changes
     */
    useEffect(() => {
      if (chatState === "loading") sentHereRef.current = true;
      else if (!isStreaming) sentHereRef.current = false;
      const anchorChanged = prevAnchorRowIdRef.current !== anchorRowId;
      const streamingStarted = isStreaming && !wasStreamingRef.current;

      prevAnchorRowIdRef.current = anchorRowId;
      wasStreamingRef.current = isStreaming;

      // Activate when a turn sent from this page starts: a new anchor appears
      // while it streams, or streaming starts with an anchor.
      if (
        sentHereRef.current &&
        anchorRowId &&
        ((anchorChanged && isStreaming) || streamingStarted)
      ) {
        requestAnimationFrame(() => {
          activate();
        });
      }

      // Note: smoothScrollActive is cleared by the 600ms timeout inside activate().
      // We intentionally do NOT clear it when streaming ends — for fast responses,
      // streaming can end before the smooth scroll animation completes, which would
      // remove the suppression too early and flash the scroll-to-bottom button.
    }, [anchorRowId, chatState, isStreaming, activate]);

    /**
     * Reset when anchor is cleared
     */
    useEffect(() => {
      if (!anchorRowId) {
        setHeight(0);
        isActiveRef.current = false;
        stopObserving();
      }
    }, [anchorRowId, setHeight, stopObserving]);

    // The scroll container outlives the spacer (a chat switch remounts only
    // the spacer), so the shared height must not outlive the spacer's element.
    useEffect(
      () => () => {
        spacerHeightRef.current = 0;
      },
      [spacerHeightRef]
    );

    /**
     * Cleanup on unmount
     */
    useEffect(() => {
      return () => {
        stopObserving();
        const scrollContainer = getScrollContainer();
        if (scrollContainer) {
          scrollContainer.dataset.smoothScrollActive = "false";
        }
      };
    }, [getScrollContainer, stopObserving]);

    return (
      <div
        ref={spacerRef}
        data-dynamic-spacer="true"
        aria-hidden="true"
        className="w-full"
        style={{
          height: "0px",
          flexShrink: 0,
        }}
      />
    );
  }
);

DynamicBottomSpacer.displayName = "DynamicBottomSpacer";

export default DynamicBottomSpacer;
