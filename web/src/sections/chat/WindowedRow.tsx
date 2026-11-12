"use client";

import React, { useEffect, useRef, useState } from "react";
import { useOptionalScrollContainer } from "@/sections/chat/ScrollContainerContext";

/** How far beyond the viewport, above and below, a row stays mounted. */
const OVERSCAN_VIEWPORTS = 2;

/**
 * `rootMargin` of an observer on the chat scroll container: `OVERSCAN_VIEWPORTS`
 * viewport heights above and below. In pixels, because browsers do not agree
 * on what a percentage of the root is.
 */
export function overscanMargin(root: HTMLElement): string {
  return `${root.clientHeight * OVERSCAN_VIEWPORTS}px 0px`;
}

/** Placeholder height of a row that has never been measured. */
const ESTIMATED_ROW_HEIGHT_PX = 320;

export interface WindowedRowProps {
  /** DOM id. The placeholder keeps it, so anchors still resolve. */
  id: string;
  className?: string;
  /** Keep the row mounted, however far it is from the viewport. */
  pinned?: boolean;
  /** Mount on the first render, before the row is known to be near the viewport. */
  initiallyMounted?: boolean;
  /** Last measured height of each row, by id. Shared by the rows of one list. */
  heightCache: Map<string, number>;
  children: React.ReactNode;
}

/**
 * A row of a long scrolling list that mounts its content only while the row
 * is within `OVERSCAN_VIEWPORTS` viewport heights of the scroll container's viewport. Away from
 * it, the row is an empty placeholder at its last measured height.
 *
 * When a row above the viewport changes height (a placeholder mounts, or
 * mounted content grows), what is on screen must stay still. Browsers with
 * native scroll anchoring (`overflow-anchor`) do this themselves. In others,
 * the row moves the scroll position by the same amount.
 *
 * A row that holds focus stays mounted. Outside a ChatScrollContainer, the
 * row always renders its content.
 */
export default function WindowedRow({
  id,
  className,
  pinned = false,
  initiallyMounted = false,
  heightCache,
  children,
}: WindowedRowProps) {
  const scrollContainer = useOptionalScrollContainer();
  const scrollContainerRef = scrollContainer?.scrollContainerRef;
  const rowRef = useRef<HTMLDivElement>(null);
  const hasFocusRef = useRef(false);
  const isIntersectingRef = useRef(initiallyMounted);
  const [nearViewport, setNearViewport] = useState(initiallyMounted);

  const mounted = !scrollContainer || pinned || nearViewport;

  useEffect(() => {
    const root = scrollContainerRef?.current;
    const row = rowRef.current;
    if (!root || !row) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        isIntersectingRef.current = entry?.isIntersecting ?? false;
        if (isIntersectingRef.current) setNearViewport(true);
        else if (!hasFocusRef.current) setNearViewport(false);
      },
      { root, rootMargin: overscanMargin(root) }
    );
    observer.observe(row);
    return () => observer.disconnect();
  }, [scrollContainerRef]);

  useEffect(() => {
    const root = scrollContainerRef?.current;
    const row = rowRef.current;
    if (!root || !row) return;

    const nativeAnchoring = CSS.supports("overflow-anchor", "auto");
    let previousHeight = row.offsetHeight;
    // Resize callbacks run after layout and before paint, so the correction
    // is never painted.
    const observer = new ResizeObserver(() => {
      const height = row.offsetHeight;
      const delta = height - previousHeight;
      previousHeight = height;
      heightCache.set(id, height);
      if (delta === 0 || nativeAnchoring) return;

      // At the end of the scroll range, the browser has already clamped the
      // position by the amount the content shrank.
      const atEnd = root.scrollTop >= root.scrollHeight - root.clientHeight - 1;
      if (delta < 0 && atEnd) return;

      const previousBottom = row.getBoundingClientRect().bottom - delta;
      if (previousBottom <= root.getBoundingClientRect().top) {
        root.scrollTop += delta;
      }
    });
    observer.observe(row);
    return () => observer.disconnect();
  }, [scrollContainerRef, heightCache, id]);

  return (
    <div
      ref={rowRef}
      id={id}
      className={className}
      style={
        mounted
          ? undefined
          : { height: heightCache.get(id) ?? ESTIMATED_ROW_HEIGHT_PX }
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
