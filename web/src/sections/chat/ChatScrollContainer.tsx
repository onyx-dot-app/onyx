"use client";

import React, {
  ForwardedRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { ScrollContainerProvider } from "@/sections/chat/ScrollContainerContext";
import { cn } from "@opal/utils";

// Size constants
const DEFAULT_ANCHOR_OFFSET_PX = 16; // 1rem
const DEFAULT_FADE_THRESHOLD_PX = 80; // 5rem
const DEFAULT_BUTTON_THRESHOLD_PX = 32; // 2rem
// After opening a chat, how long to follow content that settles below the end
// (late layout, a reply's footer), whatever the auto-scroll setting.
const OPENING_FOLLOW_MS = 1000;

// Fade configuration
const TOP_FADE_HEIGHT = "1rem";
const BOTTOM_FADE_HEIGHT = "1rem";

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

  /** Hide the scrollbar (scroll still works, just invisible) */
  hideScrollbar?: boolean;

  /** Full-width mode: edge-to-edge scroll container instead of the centered
   *  reading layout (drops the reserved scrollbar gutter). */
  fullWidth?: boolean;
}

// Build a CSS mask that fades content opacity at top/bottom edges
function buildContentMask(): string {
  // Mask uses black = visible, transparent = hidden
  // Top: fades from transparent to visible over 1rem
  // Bottom: fades from visible to transparent over 1rem
  return `linear-gradient(to bottom, transparent 0%, transparent 0rem, black ${TOP_FADE_HEIGHT}, black calc(100% - ${BOTTOM_FADE_HEIGHT}), transparent 100%)`;
}

const ChatScrollContainer = React.memo(
  React.forwardRef(
    (
      {
        children,
        anchorSelector,
        autoScroll = true,
        onScrollButtonVisibilityChange,
        sessionId,
        hideScrollbar = false,
        fullWidth = false,
      }: ChatScrollContainerProps,
      ref: ForwardedRef<ChatScrollContainerHandle>
    ) => {
      const anchorOffsetPx = DEFAULT_ANCHOR_OFFSET_PX;
      const fadeThresholdPx = DEFAULT_FADE_THRESHOLD_PX;
      const buttonThresholdPx = DEFAULT_BUTTON_THRESHOLD_PX;
      const scrollContainerRef = useRef<HTMLDivElement>(null);
      const contentWrapperRef = useRef<HTMLDivElement>(null);
      const spacerHeightRef = useRef(0);
      const endDivRef = useRef<HTMLDivElement>(null);
      const scrolledForSessionRef = useRef<string | null>(null);
      const prevAnchorSelectorRef = useRef<string | null>(null);

      const [hasContentAbove, setHasContentAbove] = useState(false);
      const [hasContentBelow, setHasContentBelow] = useState(false);
      const [isAtBottom, setIsAtBottom] = useState(true);
      const isAtBottomRef = useRef(true); // Whether to follow new content
      const autoScrollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
        null
      );
      const isAutoScrollingRef = useRef(false); // Prevent handleScroll from interfering during auto-scroll
      const followOpeningUntilRef = useRef(0);
      // Scroll position and content height that the next scroll event is
      // measured from. Record both together: shrinkage since the baseline
      // explains upward movement.
      const scrollBaselineRef = useRef({ top: 0, height: 0 });
      const [isScrollReady, setIsScrollReady] = useState(false);

      // Use refs for values that change during streaming to prevent effect re-runs
      const onScrollButtonVisibilityChangeRef = useRef(
        onScrollButtonVisibilityChange
      );
      const autoScrollRef = useRef(autoScroll);
      const previousAutoScrollRef = useRef(autoScroll);

      // Layout effect: queued rAF/observer callbacks fire after commit, so a
      // passive sync could let them scroll with a stale autoScroll flag.
      useLayoutEffect(() => {
        onScrollButtonVisibilityChangeRef.current =
          onScrollButtonVisibilityChange;
        autoScrollRef.current = autoScroll;
      }, [onScrollButtonVisibilityChange, autoScroll]);

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

        // Exclude the dynamic spacer — it's cosmetic (push-up effect) and
        // shouldn't make the system think there's real content below the viewport.
        const contentEnd =
          endDivRef.current.offsetTop - spacerHeightRef.current;
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
        setHasContentAbove(state.hasContentAbove);
        setHasContentBelow(state.hasContentBelow);

        // Show button when user is not at bottom (e.g., scrolled up)
        onScrollButtonVisibilityChangeRef.current?.(!state.isAtBottom);
        return state;
      }, [getScrollState]);

      // Scroll to bottom of content
      const scrollToBottom = useCallback(
        (behavior: ScrollBehavior = "smooth") => {
          const container = scrollContainerRef.current;
          if (!container || !endDivRef.current) return;

          if (autoScrollTimeoutRef.current !== null) {
            clearTimeout(autoScrollTimeoutRef.current);
            autoScrollTimeoutRef.current = null;
          }

          // Mark as auto-scrolling to prevent handleScroll interference
          isAutoScrollingRef.current = true;

          // Use scrollTo instead of scrollIntoView for better cross-browser support
          const targetScrollTop =
            container.scrollHeight - container.clientHeight;

          // A long smooth scroll would mount every windowed row on the way.
          // Jump to one viewport above the end, then glide the rest.
          if (behavior === "smooth") {
            const glideStart = targetScrollTop - container.clientHeight;
            if (container.scrollTop < glideStart) {
              container.scrollTop = glideStart;
            }
          }

          container.scrollTo({ top: targetScrollTop, behavior });

          // Update tracking refs
          scrollBaselineRef.current = {
            top: targetScrollTop,
            height: container.scrollHeight,
          };
          isAtBottomRef.current = true;

          // For smooth scrolling, keep isAutoScrollingRef true longer
          if (behavior === "smooth") {
            // Clear after animation likely completes (Safari smooth scroll is ~500ms)
            autoScrollTimeoutRef.current = setTimeout(() => {
              autoScrollTimeoutRef.current = null;
              isAutoScrollingRef.current = false;
              if (container) {
                // Rows that mounted on the way can move the end; settle on
                // it, unless the user scrolled away during the glide.
                if (container.scrollTop >= targetScrollTop - 1) {
                  container.scrollTo({
                    top: container.scrollHeight - container.clientHeight,
                    behavior: "instant",
                  });
                }
                scrollBaselineRef.current = {
                  top: container.scrollTop,
                  height: container.scrollHeight,
                };
              }
              // A user can interrupt the glide before it reaches the bottom.
              isAtBottomRef.current = updateScrollState().isAtBottom;
            }, 600);
          } else {
            isAutoScrollingRef.current = false;
          }
        },
        [updateScrollState]
      );

      useEffect(
        () => () => {
          if (autoScrollTimeoutRef.current !== null) {
            clearTimeout(autoScrollTimeoutRef.current);
          }
        },
        []
      );

      // Catch up on content that arrived while the typewriter paused following.
      useEffect(() => {
        const resumed = autoScroll && !previousAutoScrollRef.current;
        previousAutoScrollRef.current = autoScroll;
        if (
          resumed &&
          isAtBottomRef.current &&
          !isAutoScrollingRef.current &&
          scrollContainerRef.current?.dataset.smoothScrollActive !== "true"
        ) {
          scrollToBottom("instant");
        }
      }, [autoScroll, scrollToBottom]);

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
        // Content that shrinks (rows settling to their measured height) makes
        // the browser clamp or anchor the scroll position up by at most the
        // shrinkage. That part is layout, not the user, so only movement
        // beyond it stops following.
        const baseline = scrollBaselineRef.current;
        const shrinkage = Math.max(0, baseline.height - container.scrollHeight);
        const scrolledUp = currentScrollTop < baseline.top - shrinkage - 5; // 5px threshold to ignore micro-movements
        scrollBaselineRef.current = {
          top: currentScrollTop,
          height: container.scrollHeight,
        };

        // Only upward movement can stop following new content.
        if (scrolledUp) {
          followOpeningUntilRef.current = 0;
          isAtBottomRef.current = updateScrollState().isAtBottom;
        } else {
          // Returning to the bottom resumes following.
          const state = getScrollState();
          if (state.isAtBottom) isAtBottomRef.current = true;
          setHasContentAbove(state.hasContentAbove);
          setHasContentBelow(state.hasContentBelow);
          // Update button visibility based on actual position
          onScrollButtonVisibilityChangeRef.current?.(!state.isAtBottom);
        }
      }, [updateScrollState, getScrollState]);

      // MutationObserver (structural) + ResizeObserver (height growth).
      // Re-attached per session: the scroll element remounts on a session
      // change (it is keyed by `sessionId`).
      // NOT characterData — typewriter reveals don't change scrollHeight
      // and firing per-char thrashed auto-scroll.
      useEffect(() => {
        const container = scrollContainerRef.current;
        const contentWrapper = contentWrapperRef.current;
        if (!container) return;

        let rafId: number | null = null;

        const onContentChange = () => {
          if (rafId) return;
          rafId = requestAnimationFrame(() => {
            rafId = null;

            // Capture whether we were at bottom BEFORE content changed
            const wasAtBottom = isAtBottomRef.current;

            // Auto-scroll: follow content if we were at bottom.
            // Skip instant auto-scroll during DynamicBottomSpacer's smooth
            // scroll to avoid competing scroll commands.
            // Skip it during a smooth scroll to the bottom too: an instant
            // scroll would cut it short.
            const following =
              autoScrollRef.current ||
              performance.now() < followOpeningUntilRef.current;
            if (
              following &&
              wasAtBottom &&
              !isAutoScrollingRef.current &&
              container.dataset.smoothScrollActive !== "true"
            ) {
              // scrollToBottom handles isAutoScrollingRef and ref updates
              scrollToBottom("instant");
            }

            updateScrollState();
          });
        };

        const mutationObserver = new MutationObserver(onContentChange);
        mutationObserver.observe(container, {
          childList: true,
          subtree: true,
          attributes: true,
          attributeFilter: ["data-smooth-scroll-active"],
        });

        const resizeObserver = new ResizeObserver(onContentChange);
        resizeObserver.observe(container);
        if (contentWrapper) {
          resizeObserver.observe(contentWrapper);
        }

        return () => {
          mutationObserver.disconnect();
          resizeObserver.disconnect();
          if (rafId) cancelAnimationFrame(rafId);
        };
      }, [updateScrollState, scrollToBottom, sessionId]);

      // Handle session changes and anchor changes. A layout effect: opening a
      // chat whose messages are already rendered scrolls it into place before
      // the browser paints, so switching to a cached chat shows no blank frame.
      useLayoutEffect(() => {
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
          scrollBaselineRef.current = { top: 0, height: 0 };
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

        const scrollIntoPlace = () => {
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

          // Measure the next scroll from the new position
          scrollBaselineRef.current = {
            top: targetScrollTop,
            height: container.scrollHeight,
          };

          isAtBottomRef.current = updateScrollState().isAtBottom;

          // Mark as "at bottom" after scrolling to bottom so auto-scroll continues
          if (isLoadingExistingContent || autoScrollRef.current) {
            isAtBottomRef.current = true;
          }

          setIsScrollReady(true);
          scrolledForSessionRef.current = sessionId ?? null;
          prevAnchorSelectorRef.current = anchorSelector ?? null;
        };

        // Opening a chat: its messages are laid out already, so scroll now,
        // before paint. The content is never painted hidden or out of place.
        if (isLoadingExistingContent) {
          followOpeningUntilRef.current = performance.now() + OPENING_FOLLOW_MS;
          scrollIntoPlace();
          return;
        }

        // A new anchor within the chat: defer a tick so layout can settle.
        const timeoutId = setTimeout(scrollIntoPlace, 0);
        return () => clearTimeout(timeoutId);
      }, [sessionId, anchorSelector, anchorOffsetPx, updateScrollState]);

      // Build mask to fade content opacity at edges
      const contentMask = buildContentMask();

      return (
        <div className="flex flex-col flex-1 min-h-0 w-full relative overflow-hidden mb-1">
          <div
            key={sessionId}
            ref={scrollContainerRef}
            data-testid="chat-scroll-container"
            data-chat-scroll
            className={cn(
              "flex flex-col flex-1 min-h-0 overflow-y-auto overflow-x-hidden",
              hideScrollbar ? "no-scrollbar" : "default-scrollbar",
              // Full-width (always the case below md) drops the reserved
              // gutters so content sits flush with the chat edge; centered
              // mode keeps both-edges to avoid shift.
              !fullWidth && "md:[scrollbar-gutter:stable_both-edges]"
            )}
            onScroll={handleScroll}
            style={{
              // Apply mask to fade content opacity at edges
              maskImage: contentMask,
              WebkitMaskImage: contentMask,
            }}
          >
            <div
              ref={contentWrapperRef}
              className={cn(
                // px-2 sm:px-4 matches the input bar's horizontal padding.
                "w-full flex-1 flex flex-col items-center px-2 sm:px-4"
              )}
              data-scroll-ready={isScrollReady}
              style={{
                visibility: isScrollReady ? "visible" : "hidden",
              }}
            >
              <ScrollContainerProvider
                scrollContainerRef={scrollContainerRef}
                contentWrapperRef={contentWrapperRef}
                spacerHeightRef={spacerHeightRef}
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
