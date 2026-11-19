"use client";

import React, {
  createContext,
  ForwardedRef,
  RefObject,
  useContext,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  PLACEHOLDER_ATTRIBUTE,
  ROW_ATTRIBUTE,
  useChatScroll,
} from "@/lib/chatScroll/hooks";

/** How far beyond the viewport, above and below, a row stays mounted. */
const OVERSCAN_VIEWPORTS = 2;

/** Placeholder height of a row that has never been measured. */
const ESTIMATED_ROW_HEIGHT_PX = 320;

interface ChatScrollContextValue {
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  /** Last measured height of each row, by id. Kept per view. */
  rowHeights: Map<string, number>;
  /**
   * Reports whether `target` is within `OVERSCAN_VIEWPORTS` viewport heights
   * of the scroll container, above or below. Returns a function that stops
   * observing. Call it after the container mounts.
   */
  observeNearViewport: (
    target: Element,
    onChange: (near: boolean) => void
  ) => () => void;
}

const ChatScrollContext = createContext<ChatScrollContextValue | undefined>(
  undefined
);

/** The scroll view's context, or `undefined` outside a `ChatScrollView`. */
export function useOptionalChatScroll(): ChatScrollContextValue | undefined {
  return useContext(ChatScrollContext);
}

function useObserveNearViewport(
  scrollContainerRef: RefObject<HTMLDivElement | null>
): ChatScrollContextValue["observeNearViewport"] {
  // One observer for every row of the container, rebuilt only when the
  // container's height changes the margin.
  return useMemo(() => {
    const listeners = new Map<Element, (near: boolean) => void>();
    let observers: {
      intersection: IntersectionObserver;
      resize: ResizeObserver;
    } | null = null;
    const watch = (root: HTMLElement) =>
      new IntersectionObserver(
        (entries) => {
          for (const entry of entries)
            listeners.get(entry.target)?.(entry.isIntersecting);
        },
        // In pixels, because browsers do not agree on what a percentage of the
        // root is.
        {
          root,
          rootMargin: `${root.clientHeight * OVERSCAN_VIEWPORTS}px 0px`,
        }
      );
    return (target: Element, onChange: (near: boolean) => void) => {
      const root = scrollContainerRef.current;
      if (!root) return () => {};
      listeners.set(target, onChange);
      if (observers) {
        observers.intersection.observe(target);
      } else {
        let height = root.clientHeight;
        const current = {
          intersection: watch(root),
          resize: new ResizeObserver(() => {
            if (root.clientHeight === height) return;
            height = root.clientHeight;
            current.intersection.disconnect();
            current.intersection = watch(root);
            for (const listened of listeners.keys())
              current.intersection.observe(listened);
          }),
        };
        current.intersection.observe(target);
        current.resize.observe(root);
        observers = current;
      }
      return () => {
        listeners.delete(target);
        observers?.intersection.unobserve(target);
        if (listeners.size === 0) {
          observers?.intersection.disconnect();
          observers?.resize.disconnect();
          observers = null;
        }
      };
    };
  }, [scrollContainerRef]);
}

export interface ChatScrollViewHandle {
  scrollToBottom: () => void;
  /** Call on a send: the next turn animates its anchor to the top. */
  startTurn: () => void;
}

export interface ChatScrollViewProps {
  children: React.ReactNode;
  /** The view's identity. A change opens it again. Also the memory key. */
  viewKey?: string;
  /** Restore the view's position when it opens again. */
  rememberPosition?: boolean;
  /** Follow new content while at the end. */
  autoScroll?: boolean;
  /** Changes when a new turn appears (the last row's id). */
  turnKey?: string;
  /** DOM id of the current turn's anchor (the latest user message). */
  anchorId?: string;
  /** Rendered inside the scroll element, after the content (a sticky
   *  composer). The space below a new turn leaves room for it. */
  footer?: React.ReactNode;
  onScrollButtonVisibilityChange?: (visible: boolean) => void;
  /** Classes of the scroll element. */
  className?: string;
  style?: React.CSSProperties;
  /** Classes of the content wrapper. */
  contentClassName?: string;
  "data-testid"?: string;
}

/**
 * A scrolling chat view: follows new content, gives a sent turn space and
 * animates its anchor to the top, and returns to the saved position when the
 * view opens again. The content stays hidden until it is in place.
 *
 * Its scroll position has one owner, `useChatScroll`. Rows mark themselves
 * with `chatScrollRowProps` (or use `WindowedRow`) so the position can be
 * held and restored by row.
 */
export const ChatScrollView = React.forwardRef(function ChatScrollView(
  {
    children,
    viewKey,
    rememberPosition = true,
    autoScroll = true,
    turnKey,
    anchorId,
    footer,
    onScrollButtonVisibilityChange,
    className,
    style,
    contentClassName,
    "data-testid": testId,
  }: ChatScrollViewProps,
  ref: ForwardedRef<ChatScrollViewHandle>
) {
  const scroll = useChatScroll({
    viewKey,
    rememberPosition,
    autoScroll,
    turnKey,
    anchorId,
    onScrollButtonVisibilityChange,
  });
  const { scrollToBottom, startTurn } = scroll;
  useImperativeHandle(ref, () => ({ scrollToBottom, startTurn }), [
    scrollToBottom,
    startTurn,
  ]);

  const observeNearViewport = useObserveNearViewport(scroll.containerRef);
  const context = useMemo(
    () => ({
      scrollContainerRef: scroll.containerRef,
      rowHeights: scroll.rowHeights,
      observeNearViewport,
    }),
    [scroll.containerRef, scroll.rowHeights, observeNearViewport]
  );

  return (
    <div
      ref={scroll.containerRef}
      data-testid={testId}
      data-chat-scroll
      className={className}
      onScroll={scroll.onScroll}
      // This view keeps content still itself; browser anchoring would fight it.
      style={{ ...style, overflowAnchor: "none" }}
    >
      <div
        ref={scroll.contentRef}
        className={contentClassName}
        data-scroll-ready={scroll.revealed}
        style={{ visibility: scroll.revealed ? "visible" : "hidden" }}
      >
        <ChatScrollContext.Provider value={context}>
          {children}
        </ChatScrollContext.Provider>
        {/* Space below a sent turn, so its anchor can reach the top. */}
        <div
          ref={scroll.spacerRef}
          data-dynamic-spacer="true"
          aria-hidden="true"
          className="w-full shrink-0"
          style={{ height: 0 }}
        />
      </div>
      {footer}
    </div>
  );
});

/** Marks a row, so the scroll view can hold and restore its position by it. */
export function chatScrollRowProps(id: string) {
  return { id, [ROW_ATTRIBUTE]: "" } as const;
}

export interface WindowedRowProps {
  /** DOM id. The placeholder keeps it, so anchors still resolve. */
  id: string;
  className?: string;
  /** Keep the row mounted, however far it is from the viewport. */
  pinned?: boolean;
  /** Mount on the first render, before the row is known to be near the viewport. */
  initiallyMounted?: boolean;
  children: React.ReactNode;
}

/**
 * A row of a long scrolling list that mounts its content only while the row
 * is near the scroll view's viewport. Away from it, the row is an empty
 * placeholder at its last measured height. The scroll view keeps what is on
 * screen still when a row changes height.
 *
 * A row that holds focus stays mounted. Outside a `ChatScrollView`, the row
 * always renders its content.
 */
export function WindowedRow({
  id,
  className,
  pinned = false,
  initiallyMounted = false,
  children,
}: WindowedRowProps) {
  const scroll = useOptionalChatScroll();
  const observeNearViewport = scroll?.observeNearViewport;
  const rowHeights = scroll?.rowHeights;
  const rowRef = useRef<HTMLDivElement>(null);
  const hasFocusRef = useRef(false);
  const isIntersectingRef = useRef(initiallyMounted);
  const [nearViewport, setNearViewport] = useState(initiallyMounted);

  const mounted = !scroll || pinned || nearViewport;

  useEffect(() => {
    const row = rowRef.current;
    if (!observeNearViewport || !row) return;

    return observeNearViewport(row, (near) => {
      isIntersectingRef.current = near;
      if (near) setNearViewport(true);
      else if (!hasFocusRef.current) setNearViewport(false);
    });
  }, [observeNearViewport]);

  useEffect(() => {
    const row = rowRef.current;
    if (!row || !rowHeights) return;
    // A placeholder's size is an estimate, not the row's.
    const observer = new ResizeObserver(() => {
      if (!row.hasAttribute(PLACEHOLDER_ATTRIBUTE))
        rowHeights.set(id, row.offsetHeight);
    });
    observer.observe(row);
    return () => observer.disconnect();
  }, [rowHeights, id]);

  return (
    <div
      ref={rowRef}
      {...chatScrollRowProps(id)}
      {...(mounted ? {} : { [PLACEHOLDER_ATTRIBUTE]: "" })}
      className={className}
      style={
        mounted
          ? undefined
          : { height: rowHeights?.get(id) ?? ESTIMATED_ROW_HEIGHT_PX }
      }
      onFocus={() => {
        hasFocusRef.current = true;
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          hasFocusRef.current = false;
          // The row may have left the margin while it held focus.
          if (!isIntersectingRef.current) setNearViewport(false);
        }
      }}
    >
      {mounted ? children : null}
    </div>
  );
}
