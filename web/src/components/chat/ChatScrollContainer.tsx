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

  /** Disable fade overlays (e.g., when background image is set) */
  disableFadeOverlay?: boolean;
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
        disableFadeOverlay = false,
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
      const pendingAnchorRef = useRef<string | null>(null); // Track anchor we need to scroll to
      const hasPositionedAnchorRef = useRef(false); // Prevent re-positioning once done

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
        if (!container) {
          return {
            isAtBottom: true,
            hasContentAbove: false,
            hasContentBelow: false,
          };
        }

        // Use distance from bottom of scroll area (accounts for spacer)
        const maxScrollTop = container.scrollHeight - container.clientHeight;
        const distanceFromBottom = maxScrollTop - container.scrollTop;

        // For fade overlays, use content end (before spacer)
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

      // Update scroll state and notify parent about button visibility
      // Only updates state if values actually changed to prevent flickering
      const updateScrollState = useCallback(() => {
        const state = getScrollState();
        const prev = prevScrollStateRef.current;

        // Only update if values changed
        if (state.isAtBottom !== prev.isAtBottom) {
          setIsAtBottom(state.isAtBottom);
          // Don't override isAtBottomRef if we're currently auto-scrolling
          // (the programmatic scroll set it to true and we want to keep it)
          if (!isAutoScrollingRef.current) {
            isAtBottomRef.current = state.isAtBottom;
          }
          onScrollButtonVisibilityChangeRef.current?.(!state.isAtBottom);
        }
        if (state.hasContentAbove !== prev.hasContentAbove) {
          setHasContentAbove(state.hasContentAbove);
        }
        if (state.hasContentBelow !== prev.hasContentBelow) {
          setHasContentBelow(state.hasContentBelow);
        }

        prevScrollStateRef.current = state;
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

          // Keep isAutoScrollingRef true briefly to prevent updateScrollState from
          // overriding isAtBottomRef before the scroll settles
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
          const prev = prevScrollStateRef.current;
          // Only update if values changed
          if (state.hasContentAbove !== prev.hasContentAbove) {
            setHasContentAbove(state.hasContentAbove);
          }
          if (state.hasContentBelow !== prev.hasContentBelow) {
            setHasContentBelow(state.hasContentBelow);
          }
          // Update button visibility based on actual position
          if (state.isAtBottom !== prev.isAtBottom) {
            onScrollButtonVisibilityChangeRef.current?.(!state.isAtBottom);
          }
          prevScrollStateRef.current = state;
        }

        // Recalculate spacer during user scroll (only after initial positioning)
        if (
          anchorSelector &&
          endDivRef.current &&
          hasPositionedAnchorRef.current
        ) {
          const anchorElement = container.querySelector(
            anchorSelector
          ) as HTMLElement;
          if (anchorElement) {
            const newSpacerHeight = calcSpacerHeight(anchorElement);
            setSpacerHeight((prev) =>
              prev !== newSpacerHeight ? newSpacerHeight : prev
            );
          }
        }
      }, [anchorSelector, calcSpacerHeight, updateScrollState, getScrollState]);

      // Watch for content changes - simple approach: just scroll to bottom when content changes
      useEffect(() => {
        const container = scrollContainerRef.current;
        if (!container) return;

        let rafId: number | null = null;

        const onContentChange = () => {
          if (rafId) return;
          rafId = requestAnimationFrame(() => {
            rafId = null;

            // For streaming (has anchor), handle anchor positioning
            if (anchorSelector) {
              // Check for pending anchor that wasn't found initially
              if (pendingAnchorRef.current) {
                const pendingAnchorElement = container.querySelector(
                  pendingAnchorRef.current
                ) as HTMLElement;
                if (pendingAnchorElement && endDivRef.current) {
                  setSpacerHeight(calcSpacerHeight(pendingAnchorElement));
                  setTimeout(() => {
                    const targetScrollTop = Math.max(
                      0,
                      pendingAnchorElement.offsetTop - anchorOffsetPx
                    );
                    container.scrollTo({
                      top: targetScrollTop,
                      behavior: "smooth",
                    });
                    prevScrollTopRef.current = targetScrollTop;
                    isAtBottomRef.current = true;
                    hasPositionedAnchorRef.current = true;
                    updateScrollState();
                  }, 0);
                  pendingAnchorRef.current = null;
                  return;
                }
              }

              // Update spacer as content grows
              if (hasPositionedAnchorRef.current) {
                const anchorElement = container.querySelector(
                  anchorSelector
                ) as HTMLElement;
                if (anchorElement) {
                  const newSpacerHeight = calcSpacerHeight(anchorElement);
                  setSpacerHeight((prev) =>
                    prev !== newSpacerHeight ? newSpacerHeight : prev
                  );
                }
              }

              // Auto-scroll during streaming if at bottom
              if (autoScrollRef.current && isAtBottomRef.current) {
                scrollToBottom("instant");
              }
            } else {
              // No anchor (old conversation) - just scroll to bottom if auto-scroll enabled
              if (autoScrollRef.current && isAtBottomRef.current) {
                scrollToBottom("instant");
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

        // Initial check
        onContentChange();

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
          hasPositionedAnchorRef.current = false;
          prevScrollStateRef.current = {
            isAtBottom: true,
            hasContentAbove: false,
            hasContentBelow: false,
          };
          setSpacerHeight(0);
        }

        const needsInitialScroll = scrolledForSessionRef.current !== sessionId;
        const needsAnchorScroll = isNewAnchor && anchorSelector;

        if (!needsInitialScroll && !needsAnchorScroll) {
          prevAnchorSelectorRef.current = anchorSelector ?? null;
          return;
        }

        // No anchor = scroll to bottom (loading old conversation)
        if (!anchorSelector) {
          setIsScrollReady(true);
          scrolledForSessionRef.current = sessionId ?? null;
          prevAnchorSelectorRef.current = null;

          // Force scroll to bottom - keep trying until content is loaded
          const scrollUntilAtBottom = () => {
            const container = scrollContainerRef.current;
            if (!container) return;

            const maxScroll = container.scrollHeight - container.clientHeight;
            container.scrollTop = maxScroll;
            isAtBottomRef.current = true;
            prevScrollTopRef.current = maxScroll;

            // If there's actual scrollable content, we're done
            if (maxScroll > 50) {
              hasPositionedAnchorRef.current = true;
              updateScrollState();
            } else {
              // Content not loaded yet, try again
              requestAnimationFrame(scrollUntilAtBottom);
            }
          };

          requestAnimationFrame(scrollUntilAtBottom);
          return;
        }

        const anchorElement = container.querySelector(
          anchorSelector!
        ) as HTMLElement;
        if (!anchorElement || !endDivRef.current) {
          // Element not in DOM yet - mark as pending for MutationObserver to handle
          pendingAnchorRef.current = anchorSelector!;
          setIsScrollReady(true);
          scrolledForSessionRef.current = sessionId ?? null;
          prevAnchorSelectorRef.current = anchorSelector ?? null;
          return;
        }

        // Clear pending since we found it
        pendingAnchorRef.current = null;

        // Calculate spacer - applies to both autoScroll ON and OFF
        setSpacerHeight(calcSpacerHeight(anchorElement));

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

          // Mark as positioned to prevent MutationObserver from repositioning
          hasPositionedAnchorRef.current = true;

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
