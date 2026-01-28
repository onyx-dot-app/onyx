"use client";

import React, {
  ForwardedRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";

// Size constants
const TOP_OFFSET = 80; // Distance from viewport top where user message should land
const DEFAULT_FADE_THRESHOLD_PX = 8; // Show fade as soon as content overflows
const DEFAULT_BUTTON_THRESHOLD_PX = 32; // 2rem
const FADE_OVERLAY_HEIGHT = "h-8"; // 2rem

export interface ScrollState {
  isAtBottom: boolean;
  hasContentAbove: boolean;
  hasContentBelow: boolean;
}

export interface ChatScrollContainerHandle {
  scrollToBottom: (behavior?: ScrollBehavior) => void;
}

export interface ChatScrollContainerProps {
  children: React.ReactNode;

  /**
   * CSS selector for the element to anchor at top (e.g., "#message-123")
   * When set, positions this element at TOP_OFFSET from viewport top
   */
  anchorSelector?: string;

  /** Enable auto-scroll behavior (follow new content) */
  autoScroll?: boolean;

  /** Whether content is currently streaming (affects scroll button visibility) */
  isStreaming?: boolean;

  /** Callback when scroll button visibility should change */
  onScrollButtonVisibilityChange?: (visible: boolean) => void;

  /** Session ID - resets scroll state when changed */
  sessionId?: string;

  /** Disable fade overlays (e.g., when background image is set) */
  disableFadeOverlay?: boolean;
}

// Export TOP_OFFSET so MessageList can use it for min-height calculation
export { TOP_OFFSET };

const FadeOverlay = React.memo(
  ({ show, position }: { show: boolean; position: "top" | "bottom" }) => {
    if (!show) return null;
    const isTop = position === "top";
    return (
      <div
        aria-hidden="true"
        className={`absolute left-0 right-0 ${FADE_OVERLAY_HEIGHT} z-sticky pointer-events-none ${
          isTop ? "top-0" : "bottom-0"
        }`}
        style={{
          background: `linear-gradient(${
            isTop ? "to bottom" : "to top"
          }, var(--background-tint-01) 0%, transparent 100%)`,
        }}
      />
    );
  }
);
FadeOverlay.displayName = "FadeOverlay";

const ChatScrollContainer = React.memo(
  React.forwardRef(
    (
      {
        children,
        anchorSelector,
        autoScroll = true,
        isStreaming = false,
        onScrollButtonVisibilityChange,
        sessionId,
        disableFadeOverlay = false,
      }: ChatScrollContainerProps,
      ref: ForwardedRef<ChatScrollContainerHandle>
    ) => {
      const fadeThresholdPx = DEFAULT_FADE_THRESHOLD_PX;
      const buttonThresholdPx = DEFAULT_BUTTON_THRESHOLD_PX;
      const scrollContainerRef = useRef<HTMLDivElement>(null);
      const endDivRef = useRef<HTMLDivElement>(null);
      const scrolledForSessionRef = useRef<string | null>(null);
      const prevAnchorSelectorRef = useRef<string | null>(null);
      const pendingAnchorRef = useRef<string | null>(null);
      const hasPositionedAnchorRef = useRef(false);

      const [hasContentAbove, setHasContentAbove] = useState(false);
      const [hasContentBelow, setHasContentBelow] = useState(false);
      const [isAtBottom, setIsAtBottom] = useState(true);
      const isAtBottomRef = useRef(true);
      const isAutoScrollingRef = useRef(false);
      const prevScrollTopRef = useRef(0);
      const [isScrollReady, setIsScrollReady] = useState(false);
      // Track if user has scrolled up during streaming (disables auto-scroll)
      const userScrolledUpRef = useRef(false);
      // Track scroll height when anchor was positioned (to detect when content grows beyond initial)
      const anchorScrollHeightRef = useRef(0);

      // Use refs for values that change during streaming to prevent effect re-runs
      const onScrollButtonVisibilityChangeRef = useRef(
        onScrollButtonVisibilityChange
      );
      onScrollButtonVisibilityChangeRef.current =
        onScrollButtonVisibilityChange;
      const autoScrollRef = useRef(autoScroll);
      autoScrollRef.current = autoScroll;
      const isStreamingRef = useRef(isStreaming);
      isStreamingRef.current = isStreaming;

      // Get current scroll state
      const getScrollState = useCallback((): ScrollState => {
        const container = scrollContainerRef.current;
        if (!container) {
          return {
            isAtBottom: true,
            hasContentAbove: false,
            hasContentBelow: false,
          };
        }

        const maxScrollTop = container.scrollHeight - container.clientHeight;
        const distanceFromBottom = maxScrollTop - container.scrollTop;

        // For fade overlays, use content end
        const contentEnd =
          endDivRef.current?.offsetTop ?? container.scrollHeight;
        const viewportBottom = container.scrollTop + container.clientHeight;
        const contentBelowViewport = contentEnd - viewportBottom;

        return {
          isAtBottom: distanceFromBottom <= buttonThresholdPx,
          hasContentAbove: container.scrollTop > fadeThresholdPx,
          hasContentBelow: contentBelowViewport > fadeThresholdPx,
        };
      }, [buttonThresholdPx, fadeThresholdPx]);

      // Track previous state to avoid unnecessary re-renders
      const prevScrollStateRef = useRef<ScrollState>({
        isAtBottom: true,
        hasContentAbove: false,
        hasContentBelow: false,
      });

      // Determine if scroll button should be visible
      // During streaming, only show if user explicitly scrolled up (not just because of min-height spacer)
      // When not streaming, show based on whether user is at bottom
      const shouldShowScrollButton = useCallback((atBottom: boolean) => {
        if (isStreamingRef.current) {
          // During streaming, only show button if user scrolled up
          return userScrolledUpRef.current;
        }
        // When not streaming, show button if not at bottom
        return !atBottom;
      }, []);

      // Update scroll state and notify parent about button visibility
      const updateScrollState = useCallback(() => {
        const state = getScrollState();
        const prev = prevScrollStateRef.current;

        if (state.isAtBottom !== prev.isAtBottom) {
          setIsAtBottom(state.isAtBottom);
          if (!isAutoScrollingRef.current) {
            isAtBottomRef.current = state.isAtBottom;
          }
        }
        // Always recalculate button visibility (depends on streaming state too)
        onScrollButtonVisibilityChangeRef.current?.(
          shouldShowScrollButton(state.isAtBottom)
        );
        if (state.hasContentAbove !== prev.hasContentAbove) {
          setHasContentAbove(state.hasContentAbove);
        }
        if (state.hasContentBelow !== prev.hasContentBelow) {
          setHasContentBelow(state.hasContentBelow);
        }

        prevScrollStateRef.current = state;
      }, [getScrollState, shouldShowScrollButton]);

      // Scroll to bottom of content
      const scrollToBottom = useCallback(
        (behavior: ScrollBehavior = "smooth") => {
          const container = scrollContainerRef.current;
          if (!container || !endDivRef.current) return;

          isAutoScrollingRef.current = true;
          // Re-enable auto-scroll when user explicitly clicks scroll to bottom
          userScrolledUpRef.current = false;

          const targetScrollTop =
            container.scrollHeight - container.clientHeight;
          container.scrollTo({ top: targetScrollTop, behavior });

          prevScrollTopRef.current = targetScrollTop;
          isAtBottomRef.current = true;

          // Hide button immediately since we're now at bottom
          onScrollButtonVisibilityChangeRef.current?.(false);

          const delay = behavior === "smooth" ? 600 : 50;
          setTimeout(() => {
            isAutoScrollingRef.current = false;
            if (container) {
              prevScrollTopRef.current = container.scrollTop;
            }
          }, delay);
        },
        []
      );

      // Scroll to position anchor element at TOP_OFFSET from viewport top
      const scrollToAnchor = useCallback(
        (anchorElement: HTMLElement, behavior: ScrollBehavior = "smooth") => {
          const container = scrollContainerRef.current;
          if (!container) return;

          isAutoScrollingRef.current = true;

          const targetScrollTop = Math.max(
            0,
            anchorElement.offsetTop - TOP_OFFSET
          );
          container.scrollTo({ top: targetScrollTop, behavior });

          prevScrollTopRef.current = targetScrollTop;
          // Don't set isAtBottomRef to true - we're at the anchor position, not the bottom.
          // This prevents auto-scroll from immediately scrolling to bottom after anchor positioning.
          // Auto-scroll will only engage when user actually scrolls to bottom or content grows
          // enough to push them there.
          isAtBottomRef.current = false;

          const delay = behavior === "smooth" ? 600 : 50;
          setTimeout(() => {
            isAutoScrollingRef.current = false;
            if (container) {
              prevScrollTopRef.current = container.scrollTop;
            }
          }, delay);
        },
        []
      );

      // Expose scrollToBottom via ref
      useImperativeHandle(ref, () => ({ scrollToBottom }), [scrollToBottom]);

      // Re-evaluate button visibility when at-bottom state or streaming state changes
      useEffect(() => {
        onScrollButtonVisibilityChangeRef.current?.(
          shouldShowScrollButton(isAtBottom)
        );
      }, [isAtBottom, isStreaming, shouldShowScrollButton]);

      // Handle scroll events (user scrolls)
      const handleScroll = useCallback(() => {
        const container = scrollContainerRef.current;
        if (!container) return;

        if (isAutoScrollingRef.current) return;

        const currentScrollTop = container.scrollTop;
        const scrolledUp = currentScrollTop < prevScrollTopRef.current - 5;
        prevScrollTopRef.current = currentScrollTop;

        // Calculate if at bottom
        const maxScroll = container.scrollHeight - container.clientHeight;
        const atBottom = maxScroll - currentScrollTop <= buttonThresholdPx;

        // Track if user scrolled up during streaming (disables auto-scroll)
        if (scrolledUp && isStreamingRef.current) {
          userScrolledUpRef.current = true;
        }

        // If user scrolls back to bottom during streaming, re-enable auto-scroll
        if (atBottom && isStreamingRef.current) {
          userScrolledUpRef.current = false;
        }

        // Show/hide button based on scroll position and streaming state
        onScrollButtonVisibilityChangeRef.current?.(
          shouldShowScrollButton(atBottom)
        );

        // Update scroll state for both scroll directions
        updateScrollState();
      }, [updateScrollState, buttonThresholdPx, shouldShowScrollButton]);

      // Watch for content changes - auto-scroll when at bottom during streaming
      useEffect(() => {
        const container = scrollContainerRef.current;
        if (!container) return;

        let rafId: number | null = null;

        const onContentChange = () => {
          if (rafId) return;
          rafId = requestAnimationFrame(() => {
            rafId = null;

            // Skip if we're in the middle of a programmatic scroll
            if (isAutoScrollingRef.current) {
              return;
            }

            // Check for pending anchor that wasn't found initially
            if (pendingAnchorRef.current) {
              const pendingAnchorElement = container.querySelector(
                pendingAnchorRef.current
              ) as HTMLElement;
              if (pendingAnchorElement) {
                scrollToAnchor(pendingAnchorElement, "smooth");
                anchorScrollHeightRef.current = container.scrollHeight;
                userScrolledUpRef.current = false;
                hasPositionedAnchorRef.current = true;
                pendingAnchorRef.current = null;
                updateScrollState();
                return;
              }
            }

            // Auto-scroll to track bottom during streaming (keeps new content visible)
            // Auto-scroll only engages when:
            // 1. Auto-scroll is enabled and streaming is active
            // 2. User hasn't scrolled up (disabled auto-scroll)
            if (
              autoScrollRef.current &&
              isStreamingRef.current &&
              !userScrolledUpRef.current
            ) {
              // Find the actual content end marker (inside min-height container, after real content)
              const contentEndMarker = container.querySelector(
                '[data-content-end="true"]'
              );
              const containerRect = container.getBoundingClientRect();

              if (contentEndMarker) {
                const contentEndRect = contentEndMarker.getBoundingClientRect();
                // How far actual content extends below the visible container
                // Add buffer to keep content above the input bar area
                const contentBelowViewport =
                  contentEndRect.top - containerRect.bottom + 20;

                // Only scroll when actual content is below the viewport
                if (contentBelowViewport > 0) {
                  // Mark as auto-scrolling to prevent handleScroll interference
                  isAutoScrollingRef.current = true;
                  // Scroll just enough to bring content into view
                  const newScrollTop =
                    container.scrollTop + contentBelowViewport;
                  container.scrollTop = newScrollTop;
                  // Read back actual scroll position (browser may clamp if exceeds max)
                  prevScrollTopRef.current = container.scrollTop;
                  isAtBottomRef.current = true;
                  // Reset auto-scrolling flag after a short delay
                  setTimeout(() => {
                    isAutoScrollingRef.current = false;
                  }, 50);
                }
              }
            }

            updateScrollState();
          });
        };

        const mutationObserver = new MutationObserver(onContentChange);
        mutationObserver.observe(container, {
          childList: true,
          subtree: true,
          characterData: true,
        });

        const resizeObserver = new ResizeObserver(onContentChange);
        resizeObserver.observe(container);

        onContentChange();

        return () => {
          mutationObserver.disconnect();
          resizeObserver.disconnect();
          if (rafId) cancelAnimationFrame(rafId);
        };
      }, [scrollToAnchor, updateScrollState, scrollToBottom]);

      // Handle session changes and anchor changes
      useEffect(() => {
        const container = scrollContainerRef.current;
        if (!container) return;

        const isNewSession =
          scrolledForSessionRef.current !== null &&
          scrolledForSessionRef.current !== sessionId;
        const isNewAnchor = prevAnchorSelectorRef.current !== anchorSelector;

        // Reset on session change
        if (isNewSession) {
          scrolledForSessionRef.current = null;
          setIsScrollReady(false);
          prevScrollTopRef.current = 0;
          isAtBottomRef.current = true;
          hasPositionedAnchorRef.current = false;
          prevScrollStateRef.current = {
            isAtBottom: true,
            hasContentAbove: false,
            hasContentBelow: false,
          };
          anchorScrollHeightRef.current = 0;
          userScrolledUpRef.current = false;
        }

        const needsInitialScroll = scrolledForSessionRef.current !== sessionId;
        const needsAnchorScroll = isNewAnchor && anchorSelector;

        if (!needsInitialScroll && !needsAnchorScroll) {
          prevAnchorSelectorRef.current = anchorSelector ?? null;
          // Don't reset hasPositionedAnchorRef here - we want to keep auto-scroll disabled
          // after generation ends. It will reset on new session.
          return;
        }

        // No anchor = scroll to bottom (loading old conversation)
        if (!anchorSelector) {
          setIsScrollReady(true);
          scrolledForSessionRef.current = sessionId ?? null;
          prevAnchorSelectorRef.current = null;

          const scrollUntilAtBottom = () => {
            const container = scrollContainerRef.current;
            if (!container) return;

            const maxScroll = container.scrollHeight - container.clientHeight;
            container.scrollTop = maxScroll;
            isAtBottomRef.current = true;
            prevScrollTopRef.current = maxScroll;

            if (maxScroll > 50) {
              hasPositionedAnchorRef.current = true;
              updateScrollState();
            } else {
              requestAnimationFrame(scrollUntilAtBottom);
            }
          };

          requestAnimationFrame(scrollUntilAtBottom);
          return;
        }

        const anchorElement = container.querySelector(
          anchorSelector!
        ) as HTMLElement;
        if (!anchorElement) {
          // Element not in DOM yet - mark as pending for MutationObserver
          pendingAnchorRef.current = anchorSelector!;
          setIsScrollReady(true);
          scrolledForSessionRef.current = sessionId ?? null;
          prevAnchorSelectorRef.current = anchorSelector ?? null;
          return;
        }

        // Clear pending since we found it
        pendingAnchorRef.current = null;

        // Determine scroll behavior
        const isLoadingExistingContent =
          isNewSession || scrolledForSessionRef.current === null;
        const behavior: ScrollBehavior = isLoadingExistingContent
          ? "instant"
          : "smooth";

        // Mark as auto-scrolling BEFORE the timeout to prevent MutationObserver interference
        isAutoScrollingRef.current = true;

        // Scroll anchor to TOP_OFFSET position
        const timeoutId = setTimeout(() => {
          scrollToAnchor(anchorElement, behavior);

          // Record scroll height at anchor positioning time
          // Auto-scroll will only engage when content grows beyond this initial height
          anchorScrollHeightRef.current = container.scrollHeight;
          userScrolledUpRef.current = false;

          hasPositionedAnchorRef.current = true;

          setIsScrollReady(true);
          scrolledForSessionRef.current = sessionId ?? null;
          prevAnchorSelectorRef.current = anchorSelector ?? null;
        }, 0);

        return () => clearTimeout(timeoutId);
      }, [sessionId, anchorSelector, scrollToAnchor, updateScrollState]);

      return (
        <div className="flex flex-col flex-1 min-h-0 w-full relative overflow-hidden">
          <FadeOverlay
            show={!disableFadeOverlay && hasContentAbove}
            position="top"
          />
          <FadeOverlay
            show={!disableFadeOverlay && hasContentBelow}
            position="bottom"
          />

          <div
            key={sessionId}
            ref={scrollContainerRef}
            className="flex flex-col flex-1 min-h-0 overflow-y-auto overflow-x-hidden default-scrollbar"
            onScroll={handleScroll}
            style={{
              scrollbarGutter: "stable both-edges",
            }}
          >
            <div
              className="w-full flex-1 flex flex-col items-center"
              data-scroll-ready={isScrollReady}
              style={{
                visibility: isScrollReady ? "visible" : "hidden",
              }}
            >
              {children}

              {/* End marker for measuring content end */}
              <div ref={endDivRef} />
            </div>
          </div>
        </div>
      );
    }
  )
);

ChatScrollContainer.displayName = "ChatScrollContainer";

export default ChatScrollContainer;
