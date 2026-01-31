"use client";

import React, {
  ForwardedRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { ScrollContainerProvider } from "./ScrollContainerContext";

// Size constants
const DEFAULT_ANCHOR_OFFSET_PX = 16; // 1rem
const DEFAULT_FADE_THRESHOLD_PX = 80; // 5rem
const DEFAULT_BUTTON_THRESHOLD_PX = 32; // 2rem

// Smooth scroll animation duration estimate (Safari is ~500ms, add buffer).
const SMOOTH_SCROLL_TIMEOUT_MS = 600;

// Fade configuration
const TOP_FADE_HEIGHT = "6rem";
const TOP_OPAQUE_ZONE = "2.5rem";
const BOTTOM_FADE_HEIGHT = "16px";

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
   * CSS selector for the anchor element (e.g., "#message-123")
   * Used to scroll to a specific message position
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

// Build a CSS mask that fades content opacity at top/bottom edges
function buildContentMask(): string {
  // Mask uses black = visible, transparent = hidden
  // Top: completely transparent for first 2.5rem (~50% of 6rem), then fades to visible over remaining 3.5rem
  // Bottom: simple 16px fade
  return `linear-gradient(to bottom, transparent 0%, transparent ${TOP_OPAQUE_ZONE}, black ${TOP_FADE_HEIGHT}, black calc(100% - ${BOTTOM_FADE_HEIGHT}), transparent 100%)`;
}

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
      const contentWrapperRef = useRef<HTMLDivElement>(null);
      const endDivRef = useRef<HTMLDivElement>(null);
      const scrolledForSessionRef = useRef<string | null>(null);
      const prevAnchorSelectorRef = useRef<string | null>(null);

      const [hasContentAbove, setHasContentAbove] = useState(false);
      const [hasContentBelow, setHasContentBelow] = useState(false);
      const [isAtBottom, setIsAtBottom] = useState(true);
      const isAtBottomRef = useRef(true); // Ref for use in callbacks
      const isAutoScrollingRef = useRef(false); // Prevent handleScroll from interfering during auto-scroll
      const prevScrollTopRef = useRef(0); // Track scroll position to detect scroll direction
      const smoothScrollTimeoutRef = useRef<number | null>(null);
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

      // Update scroll state and notify parent about button visibility.
      // NOTE: This intentionally does NOT update isAtBottomRef. The ref is only
      // updated in specific scenarios (handleScroll when user scrolls up/down,
      // scrollToBottom) to preserve the "follow output" intent even when content
      // grows. This separation allows the UI state (isAtBottom) to reflect the
      // visual position while the ref tracks whether auto-scroll should continue.
      const updateScrollState = useCallback(() => {
        const state = getScrollState();
        setIsAtBottom(state.isAtBottom);
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

          // Clear any prior smooth-scroll bookkeeping.
          if (smoothScrollTimeoutRef.current != null) {
            clearTimeout(smoothScrollTimeoutRef.current);
            smoothScrollTimeoutRef.current = null;
          }

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
            // Clear after animation likely completes
            smoothScrollTimeoutRef.current = window.setTimeout(() => {
              isAutoScrollingRef.current = false;
              if (container) {
                prevScrollTopRef.current = container.scrollTop;
              }
              smoothScrollTimeoutRef.current = null;
            }, SMOOTH_SCROLL_TIMEOUT_MS);
          } else {
            isAutoScrollingRef.current = false;
          }
        },
        []
      );

      // Expose scrollToBottom via ref
      useImperativeHandle(ref, () => ({ scrollToBottom }), [scrollToBottom]);

      // Cleanup timeouts on unmount
      useEffect(() => {
        return () => {
          if (smoothScrollTimeoutRef.current != null) {
            clearTimeout(smoothScrollTimeoutRef.current);
            smoothScrollTimeoutRef.current = null;
          }
        };
      }, []);

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

        const state = getScrollState();

        // Only update isAtBottomRef when user explicitly scrolls UP (disable auto-follow),
        // or when the user returns to the bottom (re-enable auto-follow).
        //
        // This prevents content growth / programmatic scrolls from disabling auto-scroll,
        // but still allows a user scrolling back down to restore "follow output" behavior.
        if (scrolledUp || state.isAtBottom) {
          setIsAtBottom(state.isAtBottom);
          isAtBottomRef.current = state.isAtBottom;
        }

        setHasContentAbove(state.hasContentAbove);
        setHasContentBelow(state.hasContentBelow);
        onScrollButtonVisibilityChangeRef.current?.(!state.isAtBottom);
      }, [getScrollState]);

      // Watch for content changes (MutationObserver + ResizeObserver)
      useEffect(() => {
        const container = scrollContainerRef.current;
        if (!container) return;

        // Observe the content wrapper when available so we catch layout-driven
        // height changes (e.g. horizontal scrollbars in code blocks, font loads,
        // syntax highlight reflows) that don't necessarily trigger DOM mutations.
        const observedElement = contentWrapperRef.current ?? container;

        let rafId: number | null = null;

        const onContentChange = () => {
          if (rafId) return;
          rafId = requestAnimationFrame(() => {
            rafId = null;

            // Skip instant auto-scroll if DynamicBottomSpacer is doing a smooth scroll
            // (indicated by data attribute on the container)
            if (container.dataset.smoothScrollActive === "true") {
              updateScrollState();
              return;
            }

            // Capture whether we were at bottom BEFORE content changed
            const wasAtBottom = isAtBottomRef.current;

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
        mutationObserver.observe(observedElement, {
          childList: true,
          subtree: true,
          characterData: true,
        });

        // ResizeObserver for content size/layout changes
        const resizeObserver = new ResizeObserver(onContentChange);
        resizeObserver.observe(observedElement);

        return () => {
          mutationObserver.disconnect();
          resizeObserver.disconnect();
          if (rafId) cancelAnimationFrame(rafId);
        };
      }, [updateScrollState, scrollToBottom]);

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

        // Determine scroll behavior
        // New session with existing content = instant, new anchor = smooth
        const isLoadingExistingContent =
          isNewSession || scrolledForSessionRef.current === null;
        const behavior: ScrollBehavior = isLoadingExistingContent
          ? "instant"
          : "smooth";

        // Defer scroll to next tick for layout to settle
        const timeoutId = setTimeout(() => {
          let targetScrollTop: number;

          // When loading an existing conversation, scroll to bottom
          // Otherwise (e.g., anchor change during conversation), scroll to anchor
          if (isLoadingExistingContent) {
            targetScrollTop = container.scrollHeight - container.clientHeight;
          } else {
            targetScrollTop = Math.max(
              0,
              anchorElement.offsetTop - anchorOffsetPx
            );
          }

          container.scrollTo({ top: targetScrollTop, behavior });

          // Update prevScrollTopRef so scroll direction is measured from new position
          prevScrollTopRef.current = targetScrollTop;

          updateScrollState();

          // Auto-follow intent:
          // - Loading an existing conversation scrolls to bottom and should enable follow.
          // - Scrolling to an anchor is an explicit “read history” action and should
          //   disable follow until the user returns to bottom or clicks scroll-to-bottom.
          if (isLoadingExistingContent) {
            isAtBottomRef.current = true;
          } else {
            isAtBottomRef.current = false;
          }

          setIsScrollReady(true);
          scrolledForSessionRef.current = sessionId ?? null;
          prevAnchorSelectorRef.current = anchorSelector ?? null;
        }, 0);

        return () => clearTimeout(timeoutId);
      }, [sessionId, anchorSelector, anchorOffsetPx, updateScrollState]);

      // Build mask to fade content opacity at edges
      const contentMask = buildContentMask();

      return (
        <div className="flex flex-col flex-1 min-h-0 w-full relative overflow-hidden mb-[7.5rem]">
          <div
            key={sessionId}
            ref={scrollContainerRef}
            className="flex flex-col flex-1 min-h-0 overflow-y-auto overflow-x-hidden default-scrollbar"
            onScroll={handleScroll}
            style={{
              scrollbarGutter: "stable both-edges",
              // Apply mask to fade content opacity at edges
              maskImage: contentMask,
              WebkitMaskImage: contentMask,
            }}
          >
            <div
              ref={contentWrapperRef}
              className="w-full flex-1 flex flex-col items-center"
              data-scroll-ready={isScrollReady}
              style={{
                visibility: isScrollReady ? "visible" : "hidden",
              }}
            >
              <ScrollContainerProvider
                scrollContainerRef={scrollContainerRef}
                contentWrapperRef={contentWrapperRef}
              >
                {children}
              </ScrollContainerProvider>

              {/* End marker to measure content end */}
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
