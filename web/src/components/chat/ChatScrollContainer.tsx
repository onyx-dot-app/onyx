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
const DEFAULT_ANCHOR_OFFSET_PX = 16; // 1rem
const DEFAULT_FADE_THRESHOLD_PX = 80; // 5rem
const DEFAULT_BUTTON_THRESHOLD_PX = 32; // 2rem
const SCROLL_DEBOUNCE_MS = 100;
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
   * When set, positions this element at top with spacer below content
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
}

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
      }: ChatScrollContainerProps,
      ref: ForwardedRef<ChatScrollContainerHandle>
    ) => {
      const anchorOffsetPx = DEFAULT_ANCHOR_OFFSET_PX;
      const fadeThresholdPx = DEFAULT_FADE_THRESHOLD_PX;
      const buttonThresholdPx = DEFAULT_BUTTON_THRESHOLD_PX;
      const scrollContainerRef = useRef<HTMLDivElement>(null);
      const endDivRef = useRef<HTMLDivElement>(null);
      const scrolledForSessionRef = useRef<string | null>(null);
      const prevAnchorSelectorRef = useRef<string | null>(null);

      const [spacerHeight, setSpacerHeight] = useState(0);
      const [hasContentAbove, setHasContentAbove] = useState(false);
      const [hasContentBelow, setHasContentBelow] = useState(false);
      const [isAtBottom, setIsAtBottom] = useState(true);
      const isAtBottomRef = useRef(true); // Ref for use in callbacks
      const isAutoScrollingRef = useRef(false); // Prevent handleScroll from interfering during auto-scroll
      const prevScrollTopRef = useRef(0); // Track scroll position to detect scroll direction
      const [isScrollReady, setIsScrollReady] = useState(false);

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

      // Calculate spacer height to position anchor at top
      const calcSpacerHeight = useCallback(
        (anchorElement: HTMLElement): number => {
          if (!endDivRef.current || !scrollContainerRef.current) return 0;
          const contentEnd = endDivRef.current.offsetTop;
          const contentFromAnchor = contentEnd - anchorElement.offsetTop;
          return Math.max(
            0,
            scrollContainerRef.current.clientHeight -
              contentFromAnchor -
              anchorOffsetPx
          );
        },
        [anchorOffsetPx]
      );

      // Get current scroll state
      const getScrollState = useCallback((): ScrollState => {
        const container = scrollContainerRef.current;
        if (!container || !endDivRef.current) {
          return {
            isAtBottom: true,
            hasContentAbove: false,
            hasContentBelow: false,
          };
        }

        const contentEnd = endDivRef.current.offsetTop;
        const viewportBottom = container.scrollTop + container.clientHeight;
        const contentBelowViewport = contentEnd - viewportBottom;

        return {
          isAtBottom: contentBelowViewport <= buttonThresholdPx,
          hasContentAbove: container.scrollTop > fadeThresholdPx,
          hasContentBelow: contentBelowViewport > fadeThresholdPx,
        };
      }, [buttonThresholdPx, fadeThresholdPx]);

      // Update scroll state and notify parent about button visibility
      const updateScrollState = useCallback(() => {
        const state = getScrollState();
        setIsAtBottom(state.isAtBottom);
        isAtBottomRef.current = state.isAtBottom; // Keep ref in sync
        setHasContentAbove(state.hasContentAbove);
        setHasContentBelow(state.hasContentBelow);

        // Show button when user is not at bottom (e.g., scrolled up)
        onScrollButtonVisibilityChangeRef.current?.(!state.isAtBottom);
      }, [getScrollState]);

      // Scroll to bottom of content
      const scrollToBottom = useCallback(
        (behavior: ScrollBehavior = "smooth") => {
          const container = scrollContainerRef.current;
          if (!container || !endDivRef.current) return;

          // Mark as auto-scrolling to prevent handleScroll interference
          isAutoScrollingRef.current = true;

          // Use scrollTo instead of scrollIntoView for better cross-browser support
          const targetScrollTop =
            container.scrollHeight - container.clientHeight;
          container.scrollTo({ top: targetScrollTop, behavior });

          // Update tracking refs
          prevScrollTopRef.current = targetScrollTop;
          isAtBottomRef.current = true;

          // For smooth scrolling, keep isAutoScrollingRef true longer
          if (behavior === "smooth") {
            // Clear after animation likely completes (Safari smooth scroll is ~500ms)
            setTimeout(() => {
              isAutoScrollingRef.current = false;
              if (container) {
                prevScrollTopRef.current = container.scrollTop;
              }
            }, 600);
          } else {
            isAutoScrollingRef.current = false;
          }
        },
        []
      );

      // Expose scrollToBottom via ref
      useImperativeHandle(ref, () => ({ scrollToBottom }), [scrollToBottom]);

      // Re-evaluate button visibility when at-bottom state changes
      useEffect(() => {
        onScrollButtonVisibilityChangeRef.current?.(!isAtBottom);
      }, [isAtBottom]);

      // Handle scroll events (user scrolls)
      const handleScroll = useCallback(() => {
        const container = scrollContainerRef.current;
        if (!container) return;

        // Skip if this scroll was triggered by auto-scroll
        if (isAutoScrollingRef.current) return;

        const currentScrollTop = container.scrollTop;
        const scrolledUp = currentScrollTop < prevScrollTopRef.current - 5; // 5px threshold to ignore micro-movements
        prevScrollTopRef.current = currentScrollTop;

        // Only update isAtBottomRef when user explicitly scrolls UP
        // This prevents content growth or programmatic scrolls from disabling auto-scroll
        if (scrolledUp) {
          updateScrollState();
        } else {
          // Still update fade overlays, but preserve isAtBottomRef
          const state = getScrollState();
          setHasContentAbove(state.hasContentAbove);
          setHasContentBelow(state.hasContentBelow);
          // Update button visibility based on actual position
          onScrollButtonVisibilityChangeRef.current?.(!state.isAtBottom);
        }

        // Recalculate spacer for non-auto-scroll mode during user scroll
        if (!autoScrollRef.current && anchorSelector && endDivRef.current) {
          const anchorElement = container.querySelector(
            anchorSelector
          ) as HTMLElement;
          if (anchorElement) {
            setSpacerHeight(calcSpacerHeight(anchorElement));
          }
        }
      }, [anchorSelector, calcSpacerHeight, updateScrollState, getScrollState]);

      // Watch for content changes (MutationObserver + ResizeObserver)
      useEffect(() => {
        const container = scrollContainerRef.current;
        if (!container) return;

        let rafId: number | null = null;

        const onContentChange = () => {
          if (rafId) return;
          rafId = requestAnimationFrame(() => {
            rafId = null;

            // Capture whether we were at bottom BEFORE content changed
            const wasAtBottom = isAtBottomRef.current;

            // Update spacer for non-auto-scroll mode
            if (!autoScrollRef.current && anchorSelector) {
              const anchorElement = container.querySelector(
                anchorSelector
              ) as HTMLElement;
              if (anchorElement) {
                setSpacerHeight(calcSpacerHeight(anchorElement));
              }
            }

            // Auto-scroll: follow content if we were at bottom
            if (autoScrollRef.current && wasAtBottom) {
              // scrollToBottom handles isAutoScrollingRef and ref updates
              scrollToBottom("instant");
            }

            updateScrollState();
          });
        };

        // MutationObserver for content changes
        const mutationObserver = new MutationObserver(onContentChange);
        mutationObserver.observe(container, {
          childList: true,
          subtree: true,
          characterData: true,
        });

        // ResizeObserver for container size changes
        const resizeObserver = new ResizeObserver(onContentChange);
        resizeObserver.observe(container);

        return () => {
          mutationObserver.disconnect();
          resizeObserver.disconnect();
          if (rafId) cancelAnimationFrame(rafId);
        };
      }, [anchorSelector, calcSpacerHeight, updateScrollState, scrollToBottom]);

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
        }

        const shouldScroll =
          (scrolledForSessionRef.current !== sessionId || isNewAnchor) &&
          anchorSelector;

        if (!shouldScroll) {
          prevAnchorSelectorRef.current = anchorSelector ?? null;
          return;
        }

        const anchorElement = container.querySelector(
          anchorSelector!
        ) as HTMLElement;
        if (!anchorElement || !endDivRef.current) {
          setIsScrollReady(true);
          scrolledForSessionRef.current = sessionId ?? null;
          prevAnchorSelectorRef.current = anchorSelector ?? null;
          return;
        }

        // Calculate spacer
        if (!autoScrollRef.current) {
          setSpacerHeight(calcSpacerHeight(anchorElement));
        } else {
          setSpacerHeight(0);
        }

        // Determine scroll behavior
        // New session with existing content = instant, new anchor = smooth
        const isLoadingExistingContent =
          isNewSession || scrolledForSessionRef.current === null;
        const behavior: ScrollBehavior = isLoadingExistingContent
          ? "instant"
          : "smooth";

        // Defer scroll to next tick so spacer height takes effect
        const timeoutId = setTimeout(() => {
          const targetScrollTop = Math.max(
            0,
            anchorElement.offsetTop - anchorOffsetPx
          );
          container.scrollTo({ top: targetScrollTop, behavior });

          // Update prevScrollTopRef so scroll direction is measured from new position
          prevScrollTopRef.current = targetScrollTop;

          updateScrollState();

          // When autoScroll is on, assume we're "at bottom" after positioning
          // so that MutationObserver will continue auto-scrolling
          if (autoScrollRef.current) {
            isAtBottomRef.current = true;
          }

          setIsScrollReady(true);
          scrolledForSessionRef.current = sessionId ?? null;
          prevAnchorSelectorRef.current = anchorSelector ?? null;
        }, 0);

        return () => clearTimeout(timeoutId);
      }, [
        sessionId,
        anchorSelector,
        anchorOffsetPx,
        calcSpacerHeight,
        updateScrollState,
      ]);

      return (
        <div className="flex flex-col flex-1 min-h-0 w-full relative overflow-hidden mb-[7.5rem]">
          <FadeOverlay show={hasContentAbove} position="top" />
          <FadeOverlay show={hasContentBelow} position="bottom" />

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

              {/* End marker - before spacer so we can measure content end */}
              <div ref={endDivRef} />

              {/* Spacer to allow scrolling anchor to top */}
              {spacerHeight > 0 && (
                <div style={{ height: spacerHeight }} aria-hidden="true" />
              )}
            </div>
          </div>
        </div>
      );
    }
  )
);

ChatScrollContainer.displayName = "ChatScrollContainer";

export default ChatScrollContainer;
