"use client";

import {
  RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";
import {
  createScrollMemory,
  getScrollMemory,
  type HeldRow,
  type ScrollMemory,
} from "@/lib/chatScroll/memory";

/** Where a new turn's anchor stops, below the viewport's top. */
export const ANCHOR_OFFSET_PX = 16;
/** Closer than this to the end counts as at the end. */
const END_THRESHOLD_PX = 32;
const TWEEN_MS = 450;
/** After opening at the end, keep to the end while late layout settles,
 *  whatever the auto-scroll setting. */
const OPENING_STICK_MS = 1000;
/** Longest a view stays hidden while the rows around its position mount. */
const REVEAL_TIMEOUT_MS = 400;
/** A send marks the next turn for anchoring for this long. */
const TURN_PENDING_MS = 10_000;
/** A scroll this long after the user's last input is still theirs (keyboard
 *  and momentum scrolls run on after the input). */
const USER_INPUT_WINDOW_MS = 600;
/** Keys that scroll the view. */
const SCROLL_KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "PageUp",
  "PageDown",
  "Home",
  "End",
  " ",
]);

export const ROW_ATTRIBUTE = "data-chat-scroll-row";
export const PLACEHOLDER_ATTRIBUTE = "data-chat-scroll-placeholder";

type Mode =
  // Hidden: placing the view at its saved position, or the end.
  | { kind: "opening" }
  // At the end. Keeps to it while auto-scroll is on (or while the opening
  // settles); otherwise holds `held`.
  | { kind: "following"; held: HeldRow | null; stickUntil: number }
  // The user's position: holds the row at the top still.
  | { kind: "free"; held: HeldRow | null }
  // An animated move. Only its own frames write.
  | { kind: "tween" };

export interface ChatScrollOptions {
  /** The view's identity. A change opens it again. Also the memory key. */
  viewKey?: string;
  /** Restore the view's position when it opens again. */
  rememberPosition: boolean;
  /** Follow new content while at the end. */
  autoScroll: boolean;
  /** Changes when a new turn appears (the last row's id). */
  turnKey?: string;
  /** DOM id of the current turn's anchor (the latest user message). */
  anchorId?: string;
  onScrollButtonVisibilityChange?: (visible: boolean) => void;
}

export interface ChatScrollController {
  containerRef: RefObject<HTMLDivElement | null>;
  contentRef: RefObject<HTMLDivElement | null>;
  spacerRef: RefObject<HTMLDivElement | null>;
  revealed: boolean;
  /** The user gave scroll input since the view opened. Content loaded on
   *  scroll (older pages) waits for it, so a restore loads nothing extra. */
  scrolledByUser: boolean;
  rowHeights: Map<string, number>;
  onScroll: () => void;
  scrollToBottom: () => void;
  /** Call on a send: the next turn animates its anchor to the top. */
  startTurn: () => void;
  /** Call before a requested move (`scrollIntoView`): it is the user's. */
  markScrollInput: () => void;
  /** A windowed row registers how to mount it at once. Register in a layout
   *  effect, so the row is known when the view opens. */
  registerRowMounter: (row: Element, mount: () => void) => () => void;
}

function maxScrollTop(container: HTMLElement): number {
  return Math.max(0, container.scrollHeight - container.clientHeight);
}

function isAtEnd(container: HTMLElement, thresholdPx: number): boolean {
  return maxScrollTop(container) - container.scrollTop <= thresholdPx;
}

function offsetInView(element: Element, container: HTMLElement): number {
  return (
    element.getBoundingClientRect().top - container.getBoundingClientRect().top
  );
}

function findById(container: HTMLElement, id: string): HTMLElement | null {
  return container.querySelector<HTMLElement>(`#${CSS.escape(id)}`);
}

function captureTopRow(container: HTMLElement): HeldRow | null {
  const rows = container.querySelectorAll<HTMLElement>(`[${ROW_ATTRIBUTE}]`);
  const viewportTop = container.getBoundingClientRect().top;
  for (let i = 0; i < rows.length; i++) {
    const row = rows.item(i);
    const rect = row.getBoundingClientRect();
    if (rect.bottom > viewportTop) {
      return {
        rowId: row.id,
        rowIndexFromEnd: rows.length - i,
        rowOffset: rect.top - viewportTop,
      };
    }
  }
  return null;
}

function findHeldRow(
  container: HTMLElement,
  held: HeldRow
): HTMLElement | null {
  const byId = held.rowId ? findById(container, held.rowId) : null;
  if (byId) return byId;
  const rows = container.querySelectorAll<HTMLElement>(`[${ROW_ATTRIBUTE}]`);
  const index = rows.length - held.rowIndexFromEnd;
  return index >= 0 && index < rows.length ? rows.item(index) : null;
}

/** Height of what follows the content inside the scroll element (a footer). */
function trailingHeight(content: HTMLElement): number {
  let height = 0;
  for (
    let sibling = content.nextElementSibling;
    sibling;
    sibling = sibling.nextElementSibling
  ) {
    height += sibling.getBoundingClientRect().height;
  }
  return height;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

/**
 * The one owner of a chat view's scroll position. Nothing else writes
 * `scrollTop`. It follows new content, gives a sent turn space and animates
 * its anchor to the top, remembers the position per view, and keeps the
 * content on screen still while rows above it mount or change height.
 *
 * A scroll that this controller did not write, and that is not the browser
 * clamping to shorter content, is the user's. Only the user's scrolls and
 * explicit calls (send, scroll to bottom) change the mode.
 */
export function useChatScroll({
  viewKey,
  rememberPosition,
  autoScroll,
  turnKey,
  anchorId,
  onScrollButtonVisibilityChange,
}: ChatScrollOptions): ChatScrollController {
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const spacerRef = useRef<HTMLDivElement>(null);
  const [revealed, setRevealed] = useState(false);
  const [scrolledByUser, setScrolledByUser] = useState(false);

  const memory = useMemo<ScrollMemory>(
    () =>
      rememberPosition && viewKey
        ? getScrollMemory(viewKey)
        : createScrollMemory(),
    [rememberPosition, viewKey]
  );

  const memoryRef = useRef(memory);
  const autoScrollRef = useRef(autoScroll);
  const anchorIdRef = useRef(anchorId);
  const onButtonRef = useRef(onScrollButtonVisibilityChange);
  const revealTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rowMountersRef = useRef(new Map<Element, () => void>());
  // Inside a React commit (an effect), a row's state update renders before
  // paint by itself, and flushSync is not allowed.
  const committingRef = useRef(false);
  const modeRef = useRef<Mode>({ kind: "opening" });
  const revealedRef = useRef(false);
  const expectedTopRef = useRef(0);
  const spaceHeightRef = useRef(0);
  const buttonVisibleRef = useRef(false);
  const tweenFrameRef = useRef<number | null>(null);
  const turnKeyRef = useRef(turnKey);
  const pendingTurnRef = useRef<number | null>(null);
  // When the user last gave scroll input, and whether a pointer is held on
  // the view (a scrollbar drag).
  const userInputAtRef = useRef(-Infinity);
  const pointerHeldRef = useRef(false);

  // Layout effect: observer callbacks after this commit must see new props.
  useLayoutEffect(() => {
    memoryRef.current = memory;
    autoScrollRef.current = autoScroll;
    anchorIdRef.current = anchorId;
    onButtonRef.current = onScrollButtonVisibilityChange;
  }, [memory, autoScroll, anchorId, onScrollButtonVisibilityChange]);

  const write = useCallback((container: HTMLElement, top: number) => {
    container.scrollTop = top;
    // Read back: the browser clamps to the scroll range.
    expectedTopRef.current = container.scrollTop;
  }, []);

  const cancelTween = useCallback(() => {
    if (tweenFrameRef.current !== null) {
      cancelAnimationFrame(tweenFrameRef.current);
      tweenFrameRef.current = null;
    }
  }, []);

  const hold = useCallback(
    (container: HTMLElement, held: HeldRow) => {
      const row = findHeldRow(container, held);
      if (!row) return;
      const delta = offsetInView(row, container) - held.rowOffset;
      if (Math.abs(delta) > 0.5) write(container, container.scrollTop + delta);
    },
    [write]
  );

  /** Size the space below the content so the anchor can reach the top. */
  const fitSpace = useCallback((container: HTMLElement) => {
    const spacer = spacerRef.current;
    const content = contentRef.current;
    if (!spacer || !content) return;
    const id = anchorIdRef.current;
    const anchor = id ? findById(container, id) : null;
    const active =
      memoryRef.current.spaceTurnKey !== null &&
      memoryRef.current.spaceTurnKey === turnKeyRef.current;
    const height =
      anchor && active
        ? Math.max(
            0,
            Math.round(
              offsetInView(anchor, container) -
                ANCHOR_OFFSET_PX +
                container.clientHeight -
                offsetInView(spacer, container) -
                trailingHeight(content)
            )
          )
        : 0;
    if (height !== spaceHeightRef.current) {
      spaceHeightRef.current = height;
      spacer.style.height = `${height}px`;
    }
  }, []);

  const updateButton = useCallback((container: HTMLElement) => {
    const spacer = spacerRef.current;
    const content = contentRef.current;
    // A footer inside the view (a sticky composer) covers the bottom.
    const readableHeight =
      container.clientHeight - (content ? trailingHeight(content) : 0);
    const contentBelow = spacer
      ? offsetInView(spacer, container) - readableHeight
      : 0;
    const visible = revealedRef.current && contentBelow > END_THRESHOLD_PX;
    if (visible !== buttonVisibleRef.current) {
      buttonVisibleRef.current = visible;
      onButtonRef.current?.(visible);
    }
  }, []);

  const save = useCallback((container: HTMLElement) => {
    const mode = modeRef.current;
    if (
      !revealedRef.current ||
      mode.kind === "opening" ||
      mode.kind === "tween"
    )
      return;
    const sticking =
      mode.kind === "following" &&
      (autoScrollRef.current || performance.now() < mode.stickUntil);
    if (sticking || (isAtEnd(container, 1) && spaceHeightRef.current === 0)) {
      memoryRef.current.position = { kind: "end" };
      return;
    }
    const held = mode.held ?? captureTopRow(container);
    memoryRef.current.position = held ? { kind: "row", ...held } : null;
  }, []);

  /**
   * After a move ends: follow if at the end with auto-scroll on. A user who
   * scrolls to the end follows even while auto-scroll pauses (the
   * typewriter's drain); following resumes when the pause ends.
   */
  const settle = useCallback(
    (container: HTMLElement, byUser = false) => {
      const atEnd = isAtEnd(container, END_THRESHOLD_PX);
      modeRef.current =
        atEnd && (autoScrollRef.current || byUser)
          ? { kind: "following", held: null, stickUntil: 0 }
          : { kind: "free", held: captureTopRow(container) };
      updateButton(container);
      save(container);
    },
    [updateButton, save]
  );

  /**
   * A position this controller did not write is the user's only right after
   * their scroll input. Otherwise it is layout drift (rounding, clamping), and
   * the mode's position is kept. Returns whether it was the user.
   */
  const detectUserScroll = useCallback(
    (container: HTMLElement): boolean => {
      const top = container.scrollTop;
      if (Math.abs(top - expectedTopRef.current) <= 1) return false;
      const byUser =
        pointerHeldRef.current ||
        performance.now() - userInputAtRef.current < USER_INPUT_WINDOW_MS;
      expectedTopRef.current = top;
      if (!byUser || !revealedRef.current) return false;
      // A scroll the user drives (a touch fling, a smooth key scroll) can run
      // past the input window; each step keeps it the user's.
      userInputAtRef.current = performance.now();
      cancelTween();
      settle(container, true);
      return true;
    },
    [cancelTween, settle]
  );

  const reveal = useCallback(
    (container: HTMLElement) => {
      if (revealedRef.current) return;
      revealedRef.current = true;
      setRevealed(true);
      const position = memoryRef.current.position;
      // Hold the saved position itself: rows mounted for the opening have not
      // rendered yet, so the row now at the top can be off.
      modeRef.current =
        position?.kind === "row"
          ? {
              kind: "free",
              held: findById(container, position.rowId)
                ? {
                    rowId: position.rowId,
                    rowIndexFromEnd: position.rowIndexFromEnd,
                    rowOffset: position.rowOffset,
                  }
                : captureTopRow(container),
            }
          : {
              kind: "following",
              held: null,
              stickUntil: performance.now() + OPENING_STICK_MS,
            };
      updateButton(container);
      save(container);
    },
    [updateButton, save]
  );

  /**
   * Mount the placeholders in and around the viewport now, before paint, so
   * no blank row is painted (an older page that just attached, a restored
   * position). The near-viewport observer would mount them a frame later.
   * Returns whether a placeholder in view could not be mounted.
   */
  const mountNearRows = useCallback((container: HTMLElement): boolean => {
    const viewportTop = container.getBoundingClientRect().top;
    const viewportBottom = viewportTop + container.clientHeight;
    const margin = container.clientHeight;
    const mounts: (() => void)[] = [];
    let waiting = false;
    for (const placeholder of Array.from(
      container.querySelectorAll(`[${PLACEHOLDER_ATTRIBUTE}]`)
    )) {
      const rect = placeholder.getBoundingClientRect();
      if (rect.bottom <= viewportTop - margin) continue;
      if (rect.top >= viewportBottom + margin) continue;
      const mount = rowMountersRef.current.get(placeholder);
      if (mount) mounts.push(mount);
      else if (rect.bottom > viewportTop && rect.top < viewportBottom)
        waiting = true;
    }
    if (mounts.length > 0) {
      const mountAll = () => mounts.forEach((mount) => mount());
      if (committingRef.current) mountAll();
      else flushSync(mountAll);
    }
    return waiting;
  }, []);

  /** Place a view that is opening, and reveal it once its rows are in. */
  const placeOpening = useCallback(
    (container: HTMLElement) => {
      const position = memoryRef.current.position;
      // Only the saved row itself, by id: the by-rank fallback can name
      // another row once newer messages arrived. A row that is not loaded
      // (its page left the store) opens at the end; opening never waits on
      // the network.
      const savedRow =
        position?.kind === "row" ? findById(container, position.rowId) : null;
      if (position?.kind === "row" && savedRow) {
        hold(container, position);
      } else {
        write(container, maxScrollTop(container));
      }

      // Wait only for rows in view that cannot mount now.
      if (!mountNearRows(container)) reveal(container);
    },
    [hold, write, reveal, mountNearRows]
  );

  /** Keep the position the mode asks for after any layout change. */
  const reconcile = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    detectUserScroll(container);
    fitSpace(container);

    const mode = modeRef.current;
    if (mode.kind === "opening") {
      placeOpening(container);
    } else if (mode.kind === "following") {
      if (autoScrollRef.current || performance.now() < mode.stickUntil) {
        mode.held = null;
        write(container, maxScrollTop(container));
      } else if (mode.held) {
        hold(container, mode.held);
      } else {
        mode.held = captureTopRow(container);
      }
    } else if (mode.kind === "free" && mode.held) {
      hold(container, mode.held);
    }
    if (mode.kind !== "opening") mountNearRows(container);

    updateButton(container);
    save(container);
  }, [
    mountNearRows,
    detectUserScroll,
    fitSpace,
    placeOpening,
    write,
    hold,
    updateButton,
    save,
  ]);

  /** `reconcile` from an effect: React is committing. */
  const reconcileInCommit = useCallback(() => {
    committingRef.current = true;
    try {
      reconcile();
    } finally {
      committingRef.current = false;
    }
  }, [reconcile]);

  const tween = useCallback(
    (container: HTMLElement, target: () => number | null) => {
      cancelTween();
      const first = target();
      if (first === null) {
        settle(container);
        return;
      }
      if (prefersReducedMotion()) {
        write(container, first);
        settle(container);
        return;
      }
      modeRef.current = { kind: "tween" };
      const from = container.scrollTop;
      const start = performance.now();
      const step = () => {
        tweenFrameRef.current = null;
        const element = containerRef.current;
        if (!element || modeRef.current.kind !== "tween") return;
        if (detectUserScroll(element)) return;
        const t = Math.min(1, (performance.now() - start) / TWEEN_MS);
        const to = target() ?? from;
        write(element, from + (to - from) * easeOutCubic(t));
        if (t < 1) tweenFrameRef.current = requestAnimationFrame(step);
        else settle(element);
      };
      tweenFrameRef.current = requestAnimationFrame(step);
    },
    [cancelTween, settle, write, detectUserScroll]
  );

  const scrollToBottom = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    // A long animation would mount every windowed row on the way. Jump to
    // one viewport above the end, then glide the rest.
    const glideStart = maxScrollTop(container) - container.clientHeight;
    if (container.scrollTop < glideStart) write(container, glideStart);
    tween(container, () => maxScrollTop(container));
  }, [tween, write]);

  const registerRowMounter = useCallback((row: Element, mount: () => void) => {
    rowMountersRef.current.set(row, mount);
    return () => {
      rowMountersRef.current.delete(row);
    };
  }, []);

  const markScrollInput = useCallback(() => {
    userInputAtRef.current = performance.now();
    if (revealedRef.current) setScrolledByUser(true);
  }, []);

  const startTurn = useCallback(() => {
    pendingTurnRef.current = revealedRef.current ? performance.now() : null;
  }, []);

  /** Reveal after a short wait, even if rows near the position never mount. */
  const scheduleReveal = useCallback(() => {
    if (revealTimeoutRef.current !== null)
      clearTimeout(revealTimeoutRef.current);
    revealTimeoutRef.current = setTimeout(() => {
      revealTimeoutRef.current = null;
      const container = containerRef.current;
      if (container) reveal(container);
    }, REVEAL_TIMEOUT_MS);
  }, [reveal]);

  // A new view: hide it and place it before paint.
  useLayoutEffect(() => {
    const container = containerRef.current;
    cancelTween();
    modeRef.current = { kind: "opening" };
    revealedRef.current = false;
    setRevealed(false);
    setScrolledByUser(false);
    // A new view starts with its button hidden, and says so.
    buttonVisibleRef.current = false;
    onButtonRef.current?.(false);
    turnKeyRef.current = turnKey;
    pendingTurnRef.current = null;
    spaceHeightRef.current = -1;
    if (container) {
      expectedTopRef.current = container.scrollTop;
      reconcileInCommit();
    }
    scheduleReveal();
    return () => {
      if (revealTimeoutRef.current !== null)
        clearTimeout(revealTimeoutRef.current);
      revealTimeoutRef.current = null;
    };
    // Only a new view re-opens; the other inputs are read through refs.
  }, [viewKey]);

  // A new turn after a send: give it space and animate its anchor to the top.
  useLayoutEffect(() => {
    const previous = turnKeyRef.current;
    if (previous === turnKey) return;
    turnKeyRef.current = turnKey;
    const pendingSince = pendingTurnRef.current;
    pendingTurnRef.current = null;
    const container = containerRef.current;
    if (!container) return;
    const sent =
      pendingSince !== null &&
      previous !== undefined &&
      revealedRef.current &&
      performance.now() - pendingSince < TURN_PENDING_MS;
    if (!sent) {
      // A send rolled back mid-animation: its anchor is gone.
      if (modeRef.current.kind === "tween") {
        cancelTween();
        settle(container);
      }
      reconcileInCommit();
      return;
    }
    memoryRef.current.spaceTurnKey = turnKey ?? null;
    fitSpace(container);
    tween(container, () => {
      const id = anchorIdRef.current;
      const anchor = id ? findById(container, id) : null;
      if (!anchor) return null;
      const target =
        container.scrollTop +
        offsetInView(anchor, container) -
        ANCHOR_OFFSET_PX;
      return Math.min(maxScrollTop(container), Math.max(0, target));
    });
  }, [turnKey, reconcileInCommit, fitSpace, tween]);

  // Auto-scroll turned back on (the typewriter's drain ended): catch up.
  useEffect(() => {
    if (autoScroll && modeRef.current.kind === "following") reconcileInCommit();
  }, [autoScroll, reconcileInCommit]);

  // The anchor can be re-id'd by a refetch: refit the space to it.
  useEffect(() => {
    reconcileInCommit();
  }, [anchorId, reconcileInCommit]);

  useEffect(() => {
    const container = containerRef.current;
    const content = contentRef.current;
    if (!container || !content) return;

    // Resize callbacks run after layout and before paint: corrections made
    // here are never painted out of place.
    const resizeObserver = new ResizeObserver(reconcile);
    resizeObserver.observe(container);
    resizeObserver.observe(content);

    // A row that mounts at its cached height changes no size, and rows can
    // shift without the content's size changing. Check once per frame.
    let frame: number | null = null;
    const mutationObserver = new MutationObserver(() => {
      if (!revealedRef.current) {
        reconcile();
        return;
      }
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        reconcile();
      });
    });
    mutationObserver.observe(content, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: [PLACEHOLDER_ATTRIBUTE],
    });

    return () => {
      resizeObserver.disconnect();
      mutationObserver.disconnect();
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, [reconcile]);

  useEffect(() => cancelTween, [cancelTween]);

  const onScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const moved = Math.abs(container.scrollTop - expectedTopRef.current) > 1;
    // Drift is corrected at once: back to the end, or to the held row.
    if (moved && !detectUserScroll(container)) {
      reconcile();
      return;
    }
    // A fast scroll can reach rows the near-viewport observer has not
    // mounted yet.
    if (revealedRef.current) mountNearRows(container);
    updateButton(container);
  }, [detectUserScroll, reconcile, mountNearRows, updateButton]);

  // Scroll input marks the next position changes as the user's.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const markInput = markScrollInput;
    const onKeyDown = (event: KeyboardEvent) => {
      // Keys typed into a field (a composer inside the view) do not scroll.
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
    // Focus moved into the view (Tab) scrolls the focused control into view.
    container.addEventListener("focusin", markInput);
    container.addEventListener("wheel", markInput, { passive: true });
    container.addEventListener("touchmove", markInput, { passive: true });
    container.addEventListener("keydown", onKeyDown);
    container.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    return () => {
      container.removeEventListener("focusin", markInput);
      container.removeEventListener("wheel", markInput);
      container.removeEventListener("touchmove", markInput);
      container.removeEventListener("keydown", onKeyDown);
      container.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
    };
  }, [markScrollInput]);

  return {
    containerRef,
    contentRef,
    spacerRef,
    revealed,
    scrolledByUser,
    rowHeights: memory.rowHeights,
    onScroll,
    scrollToBottom,
    startTurn,
    markScrollInput,
    registerRowMounter,
  };
}
