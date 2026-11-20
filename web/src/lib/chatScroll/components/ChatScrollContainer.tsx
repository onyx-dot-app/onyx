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
import { ScrollContainerProvider } from "@/lib/chatScroll/components/ScrollContainerContext";
import { cn } from "@opal/utils";
import { CHAT_GUTTER } from "@/lib/chat/layout";
import { getChatScrollMemory } from "@/lib/chatScroll/scrollMemory";

// Size constants
const DEFAULT_FADE_THRESHOLD_PX = 80; // 5rem
const DEFAULT_BUTTON_THRESHOLD_PX = 32; // 2rem
// Longest a glide to the end may take before it settles (browsers without
// the scrollend event).
const GLIDE_TIMEOUT_MS = 800;

/**
 * following: keep to the end as content grows.
 * reading: never move; native scroll anchoring keeps the content still.
 * gliding: this view's own smooth scroll to the end runs.
 */
type ScrollMode = "following" | "reading" | "gliding";

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

  /** Pause following for a moment (the typewriter's post-finish drain)
   *  without turning it off: a view at the bottom stays there, and
   *  catches up when the pause ends. */
  pauseFollowing?: boolean;

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

  /** Rendered inside the scroll element, after the content (a sticky
   *  composer). It is not content: "at the bottom" ignores it. */
  footer?: React.ReactNode;

  /** Fade content opacity at the top and bottom edges. */
  fadeEdges?: boolean;

  /** Replace the default classes of the outer wrapper, the scroll element
   *  and the content wrapper, for a view outside the chat page. */
  className?: string;
  scrollClassName?: string;
  contentClassName?: string;

  "data-testid"?: string;
}

// A scroll this long after the user's last scroll input is still theirs
// (keyboard and momentum scrolls run on after the input).
const USER_INPUT_WINDOW_MS = 600;
// Keys that scroll the view.
const SCROLL_KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "PageUp",
  "PageDown",
  "Home",
  "End",
  " ",
]);

// Following new content scrolls to the real end, the latest turn's unfilled
// space included. So only that end counts as "at bottom" for following.
function isAtScrollEnd(container: HTMLElement, thresholdPx: number): boolean {
  return (
    container.scrollHeight - container.clientHeight - container.scrollTop <=
    thresholdPx
  );
}

// The row at the top of the viewport, and its top relative to the viewport's.
function findTopRow(
  container: HTMLElement
): { rowId: string; rowOffset: number } | null {
  const viewportTop = container.getBoundingClientRect().top;
  for (const row of Array.from(
    container.querySelectorAll<HTMLElement>('[id^="message-"]')
  )) {
    const rect = row.getBoundingClientRect();
    if (rect.bottom > viewportTop) {
      return { rowId: row.id, rowOffset: rect.top - viewportTop };
    }
  }
  return null;
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
        pauseFollowing = false,
        onScrollButtonVisibilityChange,
        sessionId,
        hideScrollbar = false,
        fullWidth = false,
        footer,
        fadeEdges = true,
        className,
        scrollClassName,
        contentClassName,
        "data-testid": testId = "chat-scroll-container",
      }: ChatScrollContainerProps,
      ref: ForwardedRef<ChatScrollContainerHandle>
    ) => {
      const fadeThresholdPx = DEFAULT_FADE_THRESHOLD_PX;
      const buttonThresholdPx = DEFAULT_BUTTON_THRESHOLD_PX;
      const scrollContainerRef = useRef<HTMLDivElement>(null);
      const contentWrapperRef = useRef<HTMLDivElement>(null);
      const endDivRef = useRef<HTMLDivElement>(null);
      const scrolledForSessionRef = useRef<string | null>(null);

      const [hasContentAbove, setHasContentAbove] = useState(false);
      const [hasContentBelow, setHasContentBelow] = useState(false);
      const [isAtBottom, setIsAtBottom] = useState(true);
      const [isScrollReady, setIsScrollReady] = useState(false);

      // The view's mode. Only the user's scroll input, a glide and the
      // opening change it; layout never does.
      const modeRef = useRef<ScrollMode>("following");
      const glideTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
        null
      );
      // When the user last gave scroll input, and whether a pointer is held
      // on the view (a scrollbar drag). Only read, never acted on directly.
      const userInputAtRef = useRef(-Infinity);
      const pointerHeldRef = useRef(false);
      const sessionIdRef = useRef(sessionId);
      const saveFrameRef = useRef<number | null>(null);

      // Use refs for values that change during streaming to prevent effect re-runs
      const onScrollButtonVisibilityChangeRef = useRef(
        onScrollButtonVisibilityChange
      );
      const autoScrollRef = useRef(autoScroll);
      const pauseFollowingRef = useRef(pauseFollowing);

      // Layout effect: queued rAF/observer callbacks fire after commit, so a
      // passive sync could let them scroll with a stale autoScroll flag.
      useLayoutEffect(() => {
        onScrollButtonVisibilityChangeRef.current =
          onScrollButtonVisibilityChange;
        autoScrollRef.current = autoScroll;
        pauseFollowingRef.current = pauseFollowing;
        sessionIdRef.current = sessionId;
      }, [
        onScrollButtonVisibilityChange,
        autoScroll,
        sessionId,
        pauseFollowing,
      ]);

      const userIsScrolling = useCallback(
        () =>
          pointerHeldRef.current ||
          performance.now() - userInputAtRef.current < USER_INPUT_WINDOW_MS,
        []
      );

      // Remember where this chat is scrolled, once per frame. Only after the
      // chat was scrolled into place: before that, the position is not the
      // user's. It only reads: saving never moves the view.
      const savePosition = useCallback(() => {
        if (saveFrameRef.current !== null) return;
        saveFrameRef.current = requestAnimationFrame(() => {
          saveFrameRef.current = null;
          const container = scrollContainerRef.current;
          const id = sessionIdRef.current;
          if (!container || !id || scrolledForSessionRef.current !== id) {
            return;
          }
          const memory = getChatScrollMemory(id);
          // 2px: a fractional scrollTop (Firefox) can sit just short of the
          // rounded end.
          if (modeRef.current === "following" || isAtScrollEnd(container, 2)) {
            memory.position = { kind: "end" };
            return;
          }
          const topRow = findTopRow(container);
          memory.position = topRow ? { kind: "row", ...topRow } : null;
        });
      }, []);

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

        // Exclude the latest turn's unfilled space (its min-height): it is
        // layout, not content below the viewport.
        let unfilled = 0;
        const turns =
          container.querySelectorAll<HTMLElement>("[data-chat-turn]");
        const lastTurn = turns.item(turns.length - 1);
        const lastRow = lastTurn?.lastElementChild;
        if (lastTurn && lastRow instanceof HTMLElement) {
          unfilled = Math.max(
            0,
            lastTurn.offsetTop +
              lastTurn.offsetHeight -
              (lastRow.offsetTop + lastRow.offsetHeight)
          );
        }
        const contentEnd = endDivRef.current.offsetTop - unfilled;
        // A footer inside the scroll element (a sticky composer) covers the
        // bottom of the viewport.
        let footerHeight = 0;
        for (
          let sibling = contentWrapperRef.current?.nextElementSibling;
          sibling;
          sibling = sibling.nextElementSibling
        ) {
          footerHeight += sibling.getBoundingClientRect().height;
        }
        const viewportBottom =
          container.scrollTop + container.clientHeight - footerHeight;
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

      const cancelGlide = useCallback(() => {
        if (glideTimeoutRef.current !== null) {
          clearTimeout(glideTimeoutRef.current);
          glideTimeoutRef.current = null;
        }
      }, []);

      /** Keep to the end at once. Never called while the user scrolls. */
      const stickToEnd = useCallback(() => {
        const container = scrollContainerRef.current;
        if (!container) return;
        container.scrollTo({
          top: container.scrollHeight - container.clientHeight,
          behavior: "instant",
        });
      }, []);

      /** A glide (or a jump) ends: follow if it reached the end. */
      const settleAtPosition = useCallback(() => {
        const container = scrollContainerRef.current;
        if (!container) return;
        modeRef.current = isAtScrollEnd(container, buttonThresholdPx)
          ? "following"
          : "reading";
        if (modeRef.current === "following") stickToEnd();
        updateScrollState();
        savePosition();
      }, [buttonThresholdPx, stickToEnd, updateScrollState, savePosition]);

      // Scroll to the end: a glide for "smooth" (a send, the button), a jump
      // otherwise. Either way the view follows afterwards.
      const scrollToBottom = useCallback(
        (behavior: ScrollBehavior = "smooth") => {
          const container = scrollContainerRef.current;
          if (!container) return;
          cancelGlide();
          if (behavior !== "smooth") {
            stickToEnd();
            modeRef.current = "following";
            updateScrollState();
            savePosition();
            return;
          }

          modeRef.current = "gliding";
          const targetScrollTop =
            container.scrollHeight - container.clientHeight;
          // A long smooth scroll would mount every windowed row on the way.
          // From farther than two viewports, jump to one viewport above the
          // end and glide the rest. A send, about one viewport away, glides
          // all the way.
          const glideStart =
            container.scrollTop < targetScrollTop - 2 * container.clientHeight
              ? targetScrollTop - container.clientHeight
              : container.scrollTop;
          if (container.scrollTop < glideStart) {
            container.scrollTop = glideStart;
          }
          container.scrollTo({ top: targetScrollTop, behavior: "smooth" });

          // The glide ends on scrollend; the timeout covers browsers without
          // it and a glide that goes nowhere.
          const finish = () => {
            container.removeEventListener("scrollend", finish);
            cancelGlide();
            if (container !== scrollContainerRef.current) return;
            if (modeRef.current === "gliding") settleAtPosition();
          };
          container.addEventListener("scrollend", finish, { once: true });
          glideTimeoutRef.current = setTimeout(finish, GLIDE_TIMEOUT_MS);
        },
        [
          cancelGlide,
          stickToEnd,
          updateScrollState,
          savePosition,
          settleAtPosition,
        ]
      );

      useEffect(
        () => () => {
          cancelGlide();
          if (saveFrameRef.current !== null) {
            cancelAnimationFrame(saveFrameRef.current);
          }
        },
        [cancelGlide]
      );

      // Catch up on content that arrived while following was paused (the
      // typewriter's drain) or off.
      const followingActive = autoScroll && !pauseFollowing;
      useEffect(() => {
        if (followingActive && modeRef.current === "following") {
          stickToEnd();
          updateScrollState();
        }
      }, [followingActive, stickToEnd, updateScrollState]);

      // Expose scrollToBottom via ref
      useImperativeHandle(ref, () => ({ scrollToBottom }), [scrollToBottom]);

      // Re-evaluate button visibility when at-bottom state changes
      useEffect(() => {
        onScrollButtonVisibilityChangeRef.current?.(!isAtBottom);
      }, [isAtBottom]);

      // A scroll event. A move is the user's only right after their scroll
      // input: then the position sets the mode. Any other move is layout
      // (Firefox clamps the position while content briefly shrinks, a glide
      // runs, anchoring adjusts), and only a following view reacts, by
      // returning to the end.
      const handleScroll = useCallback(() => {
        const container = scrollContainerRef.current;
        if (!container) return;

        if (userIsScrolling()) {
          // A fling keeps moving past its last input; each step stays the
          // user's. It also ends a glide.
          userInputAtRef.current = performance.now();
          cancelGlide();
          modeRef.current = isAtScrollEnd(container, buttonThresholdPx)
            ? "following"
            : "reading";
        } else if (
          modeRef.current === "following" &&
          autoScrollRef.current &&
          !pauseFollowingRef.current &&
          !isAtScrollEnd(container, 2)
        ) {
          stickToEnd();
        }
        updateScrollState();
        savePosition();
      }, [
        userIsScrolling,
        cancelGlide,
        buttonThresholdPx,
        stickToEnd,
        updateScrollState,
        savePosition,
      ]);

      // Scroll input marks the next moves as the user's. A focus move counts:
      // the browser scrolls the focused element into view. Re-attached per
      // session: the scroll element remounts (it is keyed by sessionId).
      useEffect(() => {
        const container = scrollContainerRef.current;
        if (!container) return;
        const markInput = () => {
          userInputAtRef.current = performance.now();
        };
        const onKeyDown = (event: KeyboardEvent) => {
          // Keys typed into a field inside the view do not scroll it.
          const target = event.target;
          const typing =
            target instanceof HTMLElement &&
            (target.isContentEditable || target.closest("input, textarea"));
          if (!typing && SCROLL_KEYS.has(event.key)) markInput();
        };
        const onPointerDown = () => {
          pointerHeldRef.current = true;
          markInput();
        };
        const onPointerUp = () => {
          if (!pointerHeldRef.current) return;
          pointerHeldRef.current = false;
          markInput();
        };
        container.addEventListener("wheel", markInput, { passive: true });
        container.addEventListener("touchmove", markInput, { passive: true });
        container.addEventListener("keydown", onKeyDown);
        container.addEventListener("focusin", markInput);
        container.addEventListener("pointerdown", onPointerDown);
        window.addEventListener("pointerup", onPointerUp);
        window.addEventListener("pointercancel", onPointerUp);
        return () => {
          container.removeEventListener("wheel", markInput);
          container.removeEventListener("touchmove", markInput);
          container.removeEventListener("keydown", onKeyDown);
          container.removeEventListener("focusin", markInput);
          container.removeEventListener("pointerdown", onPointerDown);
          window.removeEventListener("pointerup", onPointerUp);
          window.removeEventListener("pointercancel", onPointerUp);
        };
      }, [sessionId]);

      // Content changes (structure or size), batched per frame. A following
      // view keeps to the end; with following off (auto-scroll off while a
      // reply runs), growth that leaves the end makes the view a reading one,
      // so a later resume never jumps. Not while the user scrolls.
      // NOT characterData: firing per character thrashed auto-scroll. Text
      // that grows inside the latest turn's min-height changes no scroll
      // height, so the ResizeObserver also watches that turn's rows.
      // oxlint-disable-next-line react-doctor/effect-needs-cleanup -- the cleanup disconnects rowObserver, which owns every row observe.
      useEffect(() => {
        const container = scrollContainerRef.current;
        const contentWrapper = contentWrapperRef.current;
        if (!container) return;

        let rafId: number | null = null;
        const onContentChange = () => {
          if (rafId) return;
          rafId = requestAnimationFrame(() => {
            rafId = null;
            observeLatestTurnRows();
            if (modeRef.current === "following" && !userIsScrolling()) {
              if (autoScrollRef.current && !pauseFollowingRef.current) {
                stickToEnd();
              } else if (
                !autoScrollRef.current &&
                !isAtScrollEnd(container, buttonThresholdPx)
              ) {
                modeRef.current = "reading";
              }
            }
            updateScrollState();
            savePosition();
          });
        };

        const mutationObserver = new MutationObserver(onContentChange);
        mutationObserver.observe(container, { childList: true, subtree: true });
        const resizeObserver = new ResizeObserver(onContentChange);
        // The latest turn's rows: they change as turns arrive. Only rows
        // new to the set are observed: observing fires a callback.
        const rowObserver = new ResizeObserver(onContentChange);
        let observedRows = new Set<Element>();
        const observeLatestTurnRows = () => {
          const turns = container.querySelectorAll("[data-chat-turn]");
          const rows = new Set(
            Array.from(turns.item(turns.length - 1)?.children ?? [])
          );
          for (const row of observedRows) {
            if (!rows.has(row)) rowObserver.unobserve(row);
          }
          for (const row of rows) {
            if (!observedRows.has(row)) rowObserver.observe(row);
          }
          observedRows = rows;
        };

        resizeObserver.observe(container);
        if (contentWrapper) {
          resizeObserver.observe(contentWrapper);
          // A footer (a sticky composer) that grows covers more of the
          // viewport, which changes the scroll-to-bottom button.
          for (
            let footer = contentWrapper.nextElementSibling;
            footer;
            footer = footer.nextElementSibling
          ) {
            resizeObserver.observe(footer);
          }
        }
        observeLatestTurnRows();

        return () => {
          mutationObserver.disconnect();
          resizeObserver.disconnect();
          rowObserver.disconnect();
          if (rafId) cancelAnimationFrame(rafId);
        };
      }, [
        userIsScrolling,
        stickToEnd,
        updateScrollState,
        savePosition,
        buttonThresholdPx,
        sessionId,
      ]);

      // Opening a chat: place it at its saved row (when that row is loaded)
      // or at the end, before paint, then show it. A layout effect: a cached
      // chat is never painted hidden or out of place. Only rows already
      // loaded count, so opening never waits on the network.
      useLayoutEffect(() => {
        const container = scrollContainerRef.current;
        if (!container) return;
        if (scrolledForSessionRef.current === (sessionId ?? null)) return;

        // A new chat: reset before placing it.
        if (scrolledForSessionRef.current !== null) {
          setIsScrollReady(false);
          cancelGlide();
          modeRef.current = "following";
        }
        // No messages yet: nothing to place, so show the view.
        if (!anchorSelector) {
          setIsScrollReady(true);
          return;
        }

        const saved = sessionId
          ? getChatScrollMemory(sessionId).position
          : null;
        const savedRow =
          saved?.kind === "row"
            ? container.querySelector<HTMLElement>(
                `#${CSS.escape(saved.rowId)}`
              )
            : null;
        if (savedRow && saved?.kind === "row") {
          container.scrollTo({
            top:
              container.scrollTop +
              savedRow.getBoundingClientRect().top -
              container.getBoundingClientRect().top -
              saved.rowOffset,
            behavior: "instant",
          });
          modeRef.current = isAtScrollEnd(container, buttonThresholdPx)
            ? "following"
            : "reading";
        } else {
          stickToEnd();
          modeRef.current = "following";
        }
        updateScrollState();
        setIsScrollReady(true);
        scrolledForSessionRef.current = sessionId ?? null;
      }, [
        sessionId,
        anchorSelector,
        buttonThresholdPx,
        cancelGlide,
        stickToEnd,
        updateScrollState,
      ]);

      // Build mask to fade content opacity at edges
      const contentMask = buildContentMask();

      return (
        <div
          className={
            className ??
            "flex flex-col flex-1 min-h-0 w-full relative overflow-hidden mb-1"
          }
        >
          <div
            key={sessionId}
            ref={scrollContainerRef}
            data-testid={testId}
            data-chat-scroll
            className={
              scrollClassName ??
              cn(
                // A size container: the latest turn's min-height is in cqh.
                "flex flex-col flex-1 min-h-0 overflow-y-auto overflow-x-hidden [container-type:size]",
                hideScrollbar ? "no-scrollbar" : "default-scrollbar",
                // Full-width (always the case below md) drops the reserved
                // gutters so content sits flush with the chat edge; centered
                // mode keeps both-edges to avoid shift.
                !fullWidth && "md:[scrollbar-gutter:stable_both-edges]"
              )
            }
            onScroll={() => {
              handleScroll();
              savePosition();
            }}
            style={
              fadeEdges
                ? {
                    // Apply mask to fade content opacity at edges
                    maskImage: contentMask,
                    WebkitMaskImage: contentMask,
                  }
                : undefined
            }
          >
            <div
              ref={contentWrapperRef}
              className={
                contentClassName ??
                cn("w-full flex-1 flex flex-col items-center", CHAT_GUTTER)
              }
              data-scroll-ready={isScrollReady}
              style={{
                visibility: isScrollReady ? "visible" : "hidden",
              }}
            >
              <ScrollContainerProvider
                scrollContainerRef={scrollContainerRef}
                contentWrapperRef={contentWrapperRef}
                sessionId={sessionId}
              >
                {children}
              </ScrollContainerProvider>

              {/* End marker to measure content end */}
              <div ref={endDivRef} />
            </div>
            {footer}
          </div>
        </div>
      );
    }
  )
);

ChatScrollContainer.displayName = "ChatScrollContainer";

export default ChatScrollContainer;
