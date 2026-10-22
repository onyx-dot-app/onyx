"use client";

import "@opal/layouts/sticky-box/styles.css";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@opal/utils";
import { spacingToRem } from "@opal/shared";
import type { Spacing } from "@opal/types";

type StickyEdge = "top" | "bottom";

interface StickyBoxProps {
  /** The edge of the scroll container the box pins to. @default "top" */
  stick?: StickyEdge;
  /** Gap kept from that edge while pinned, as a spacing step. @default 0 */
  inset?: Spacing;
  /**
   * Whether the box sticks at all. Off, it is a plain block in the flow, so
   * a box can stick only while it has something to say.
   *
   * @default true
   */
  active?: boolean;
  /**
   * Cast a shadow while pinned. The shadow follows the shape of what is
   * inside, so a rounded card casts a rounded shadow.
   */
  shadow?: boolean;
  children: React.ReactNode;
  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
}

/** The nearest ancestor that scrolls, which is what a sticky box pins to. */
function findScrollParent(element: HTMLElement): Element | null {
  let node: HTMLElement | null = element.parentElement;
  while (node) {
    const { overflowY } = getComputedStyle(node);
    if (overflowY === "auto" || overflowY === "scroll") return node;
    node = node.parentElement;
  }
  return null;
}

/**
 * A block that pins to the top or bottom of its scroll container as the page
 * scrolls past it, on the `--z-sticky` level.
 *
 * CSS has no "is pinned" state, so `shadow` watches the box with an
 * IntersectionObserver: fully visible inside the scroll container it is in
 * the flow; once its pinned edge sits on the container's edge (plus the
 * inset) it is pinned, and `data-stuck` goes on the root.
 *
 * `position: sticky` needs the scroll container to be an ancestor with no
 * `overflow: hidden` between the two; the box cannot fix that for a caller.
 */
function StickyBox({
  stick = "top",
  inset = 0,
  active = true,
  shadow = false,
  children,
  ref,
}: StickyBoxProps) {
  const [stuck, setStuck] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  const setRoot = useCallback(
    (node: HTMLDivElement | null) => {
      rootRef.current = node;
      if (typeof ref === "function") ref(node);
      else if (ref) ref.current = node;
    },
    [ref]
  );

  useEffect(() => {
    const element = rootRef.current;
    if (!element || !active || !shadow) {
      setStuck(false);
      return;
    }
    const root = findScrollParent(element);
    // The applied offset in px, whatever unit the inset resolved to.
    const offset = parseFloat(getComputedStyle(element)[stick]) || 0;
    const margin =
      stick === "top"
        ? `-${offset + 1}px 0px 0px 0px`
        : `0px 0px -${offset + 1}px 0px`;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        const bounds = entry.rootBounds;
        if (!bounds) {
          setStuck(false);
          return;
        }
        // Less than fully visible on the pinned side only: a box scrolling
        // in from the other side is not pinned, just not there yet.
        const rect = entry.boundingClientRect;
        const atEdge =
          stick === "top"
            ? rect.top <= bounds.top + offset + 1
            : rect.bottom >= bounds.bottom - offset - 1;
        setStuck(entry.intersectionRatio < 1 && atEdge);
      },
      { root, threshold: [1], rootMargin: margin }
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [active, shadow, stick, inset]);

  return (
    <div
      ref={setRoot}
      className={cn("opal-sticky-box", active && "opal-sticky-box-active")}
      data-stick={stick}
      data-stuck={stuck || undefined}
      style={active ? { [stick]: spacingToRem(inset) } : undefined}
    >
      {children}
    </div>
  );
}

export { StickyBox, type StickyBoxProps, type StickyEdge };
