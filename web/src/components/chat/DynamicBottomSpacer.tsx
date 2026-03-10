"use client";

import React, { useEffect, useRef, useCallback } from "react";
import { useCurrentChatState } from "@/app/app/stores/useChatSessionStore";
import { useScrollContainer } from "@/components/chat/ScrollContainerContext";

// Small offset from the top of the scroll viewport where the anchor should appear.
// The header is outside the scroll container, so when scrolled to the bottom
// during the push-up effect, we only need minimal padding.
const ANCHOR_TOP_OFFSET_PX = 16;

// Duration of smooth scroll animation (browser default is ~400-500ms, we add buffer)
const SMOOTH_SCROLL_DURATION_MS = 600;

// How long to wait after content stops changing before deactivating
const CONTENT_SETTLED_DEBOUNCE_MS = 500;

export interface DynamicBottomSpacerProps {
  /**
   * Node ID of the anchor message (the new user message)
   */
  anchorNodeId?: number;
}

/**
 * DynamicBottomSpacer creates a "fresh chat" effect by filling the space
 * below messages to push content up when a new round starts.
 * Uses ResizeObserver to efficiently detect content changes instead of polling.
 */
const DynamicBottomSpacer = React.memo(
  ({ anchorNodeId }: DynamicBottomSpacerProps) => {
    const spacerRef = useRef<HTMLDivElement>(null);
    const chatState = useCurrentChatState();
    const isStreaming = chatState === "streaming" || chatState === "loading";

    // Get scroll container refs from context (provided by ChatScrollContainer)
    const { scrollContainerRef, contentWrapperRef, spacerHeightRef } =
      useScrollContainer();

    // Track state with refs to avoid re-renders
    const isActiveRef = useRef(false);
    const initialSpacerHeightRef = useRef(0);
    const initialContentHeightRef = useRef(0);
    const currentSpacerHeightRef = useRef(0);
    const prevAnchorNodeIdRef = useRef<number | undefined>(undefined);
    const wasStreamingRef = useRef(false);
    const resizeObserverRef = useRef<ResizeObserver | null>(null);
    const settledTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
      null
    );

    /**
     * Set spacer height directly on DOM (no re-renders)
     */
    const setHeight = useCallback(
      (height: number) => {
        const h = Math.max(0, Math.round(height));
        currentSpacerHeightRef.current = h;
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
     * Get content height (total scrollHeight minus current spacer height)
     */
    const getContentHeight = useCallback(() => {
      const scrollContainer = getScrollContainer();
      if (!scrollContainer) return 0;
      return scrollContainer.scrollHeight - currentSpacerHeightRef.current;
    }, [getScrollContainer]);

    /**
     * Update spacer height based on content growth
     */
    const updateSpacerHeight = useCallback(() => {
      if (!isActiveRef.current) return;

      const currentContentHeight = getContentHeight();
      const contentGrowth =
        currentContentHeight - initialContentHeightRef.current;

      // New spacer height = initial spacer - content growth
      const newHeight = initialSpacerHeightRef.current - contentGrowth;

      if (newHeight <= 0) {
        setHeight(0);
        isActiveRef.current = false;
      } else {
        setHeight(newHeight);
      }
    }, [setHeight, getContentHeight]);

    /**
     * Stop observing and clean up
     */
    const stopObserving = useCallback(() => {
      if (resizeObserverRef.current) {
        resizeObserverRef.current.disconnect();
        resizeObserverRef.current = null;
      }
      if (settledTimeoutRef.current) {
        clearTimeout(settledTimeoutRef.current);
        settledTimeoutRef.current = null;
      }
    }, []);

    /**
     * Start observing content changes with ResizeObserver
     */
    const startObserving = useCallback(() => {
      const scrollContainer = getScrollContainer();
      if (!scrollContainer || resizeObserverRef.current) return;

      resizeObserverRef.current = new ResizeObserver(() => {
        // Content size changed - update spacer
        updateSpacerHeight();

        // Reset the "settled" timeout - content is still changing
        if (settledTimeoutRef.current) {
          clearTimeout(settledTimeoutRef.current);
        }

        // After content stops changing for CONTENT_SETTLED_DEBOUNCE_MS, deactivate
        settledTimeoutRef.current = setTimeout(() => {
          // Only deactivate if streaming has ended
          if (!wasStreamingRef.current) {
            isActiveRef.current = false;
            stopObserving();
          }
        }, CONTENT_SETTLED_DEBOUNCE_MS);
      });

      // Observe the content wrapper using context ref
      if (contentWrapperRef.current) {
        resizeObserverRef.current.observe(contentWrapperRef.current);
      }
    }, [
      getScrollContainer,
      updateSpacerHeight,
      stopObserving,
      contentWrapperRef,
    ]);

    /**
     * Activate the spacer - calculate initial height and scroll to bottom
     */
    const activate = useCallback(() => {
      if (!anchorNodeId) return;

      // If already active, stop the current observation to restart fresh
      if (isActiveRef.current) {
        stopObserving();
        isActiveRef.current = false;
      }

      const anchor = document.getElementById(`message-${anchorNodeId}`);
      if (!anchor) return;

      const scrollContainer = getScrollContainer();
      if (!scrollContainer) return;

      // Get measurements first (before modifying spacer)
      const viewportHeight = scrollContainer.clientHeight;
      const currentSpacerHeight = currentSpacerHeightRef.current;

      // Calculate content height (scrollHeight minus current spacer)
      const contentHeight = scrollContainer.scrollHeight - currentSpacerHeight;

      // Calculate anchor's position using getBoundingClientRect for accuracy
      const containerRect = scrollContainer.getBoundingClientRect();
      const anchorRect = anchor.getBoundingClientRect();

      // Anchor's visual offset from the scroll container's top edge
      const anchorVisualOffset = anchorRect.top - containerRect.top;

      // Anchor's absolute position in the scrollable content
      const anchorOffsetInContent =
        anchorVisualOffset + scrollContainer.scrollTop;

      // Calculate spacer height needed to position anchor just below the top offset
      // when scrolled to the absolute bottom.
      const spacerHeight =
        anchorOffsetInContent -
        contentHeight +
        viewportHeight -
        ANCHOR_TOP_OFFSET_PX;

      // If spacer height is <= 0, no push-up effect is needed.
      // This naturally handles new chats and short conversations where
      // the anchor is already positioned appropriately.
      if (spacerHeight <= 0) return;

      // Store initial content height for tracking content growth during streaming
      initialContentHeightRef.current = contentHeight;
      initialSpacerHeightRef.current = spacerHeight;
      isActiveRef.current = true;

      // Set the spacer height
      setHeight(spacerHeight);

      // Tell ChatScrollContainer to not do instant auto-scroll during smooth scroll
      scrollContainer.dataset.smoothScrollActive = "true";

      // Start observing content changes
      startObserving();

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
      anchorNodeId,
      setHeight,
      getScrollContainer,
      startObserving,
      stopObserving,
    ]);

    /**
     * Main effect: detect streaming start/stop and anchor changes
     */
    useEffect(() => {
      const anchorChanged = prevAnchorNodeIdRef.current !== anchorNodeId;
      const streamingStarted = isStreaming && !wasStreamingRef.current;

      prevAnchorNodeIdRef.current = anchorNodeId;
      wasStreamingRef.current = isStreaming;

      // Activate when: new anchor appears while streaming, or streaming starts with anchor
      if (
        (anchorChanged && anchorNodeId && isStreaming) ||
        (streamingStarted && anchorNodeId)
      ) {
        requestAnimationFrame(() => {
          activate();
        });
      }

      // Note: smoothScrollActive is cleared by the 600ms timeout inside activate().
      // We intentionally do NOT clear it when streaming ends — for fast responses,
      // streaming can end before the smooth scroll animation completes, which would
      // remove the suppression too early and flash the scroll-to-bottom button.
    }, [anchorNodeId, isStreaming, activate]);

    /**
     * Reset when anchor is cleared
     */
    useEffect(() => {
      if (!anchorNodeId) {
        setHeight(0);
        isActiveRef.current = false;
        initialSpacerHeightRef.current = 0;
        initialContentHeightRef.current = 0;
        stopObserving();
      }
    }, [anchorNodeId, setHeight, stopObserving]);

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
