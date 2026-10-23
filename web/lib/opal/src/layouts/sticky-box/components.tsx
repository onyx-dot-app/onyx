"use client";

import "@opal/layouts/sticky-box/styles.css";
import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { cn } from "@opal/utils";
import { spacingToRem } from "@opal/shared";
import type { Spacing } from "@opal/types";

type StickyEdge = "top" | "bottom";

interface StickyBoxItemHandle {
  /**
   * Smoothly scrolls the container until the box's place in the flow sits
   * where it is pinned, so turning `active` off then shows no jump. Resolves
   * when the scroll ends, at once if the box is not pinned.
   */
  scrollToPlace: () => Promise<void>;
}

interface StickyBoxItemProps {
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
  /** Actions on the box, such as `scrollToPlace`. */
  handleRef?: React.Ref<StickyBoxItemHandle>;
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

// Covers browsers without `scrollend`.
const SCROLL_END_FALLBACK_MS = 600;

/** Smooth-scrolls the container (or the page) by `delta`; resolves at the end. */
function scrollBy(root: Element | null, delta: number): Promise<void> {
  return new Promise((resolve) => {
    const target: Element | Window = root ?? window;
    const reduce = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    let timer = 0;
    function done() {
      window.clearTimeout(timer);
      target.removeEventListener("scrollend", done);
      resolve();
    }
    target.addEventListener("scrollend", done);
    timer = window.setTimeout(done, SCROLL_END_FALLBACK_MS);
    target.scrollBy({ top: delta, behavior: reduce ? "auto" : "smooth" });
  });
}

/**
 * A block that pins to the top or bottom of its scroll container as the page
 * scrolls past it, on the `--z-sticky` level. Inside a `StickyBox.Root`, a
 * top item pins below the root's visible top (`--sticky-box-top`), e.g. under
 * a sticky settings header; without one, at the container's edge.
 *
 * CSS has no "is pinned" state, so `shadow` watches the box with an
 * IntersectionObserver: fully visible inside the scroll container it is in
 * the flow; once its pinned edge sits on the container's edge (plus the
 * inset) it is pinned, and `data-stuck` goes on the root.
 *
 * `position: sticky` needs the scroll container to be an ancestor with no
 * `overflow: hidden` between the two; the box cannot fix that for a caller.
 */
function StickyBoxItem({
  stick = "top",
  inset = 0,
  active = true,
  shadow = false,
  children,
  ref,
  handleRef,
}: StickyBoxItemProps) {
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

  useImperativeHandle(
    handleRef,
    () => ({
      scrollToPlace: async () => {
        const element = rootRef.current;
        if (!element || !active) return;
        // A pinned box reports its pinned position. Unstuck for one
        // synchronous measure, it reports its place in the flow; nothing
        // paints in between.
        const pinned = element.getBoundingClientRect();
        element.style.position = "static";
        const place = element.getBoundingClientRect();
        element.style.position = "";
        const delta =
          stick === "top"
            ? place.top - pinned.top
            : place.bottom - pinned.bottom;
        // Under 1px apart, the box is already in its place.
        if (Math.abs(delta) < 1) return;
        await scrollBy(findScrollParent(element), delta);
      },
    }),
    [active, stick]
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
      style={
        active
          ? {
              [stick]:
                stick === "top"
                  ? `calc(var(--sticky-box-top, 0px) + ${spacingToRem(inset)})`
                  : spacingToRem(inset),
            }
          : undefined
      }
    >
      {children}
    </div>
  );
}

interface StickyBoxRootProps {
  children: React.ReactNode;
  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
}

/**
 * The region its `StickyBox.Item`s pin inside. It sets `--sticky-box-top` to
 * the region's visible top: below the sticky settings header, whose height
 * `SettingsLayouts.Header` publishes, else the container's edge.
 *
 * An item still sticks only within its own parent's box, so the parent must
 * span the region.
 */
function StickyBoxRoot({ children, ref }: StickyBoxRootProps) {
  return (
    <div
      ref={ref}
      className="opal-sticky-box-root"
      // SAFETY: CSSProperties has no custom properties; this sets one only.
      style={
        {
          "--sticky-box-top": "var(--settings-header-height, 0px)",
        } as React.CSSProperties
      }
    >
      {children}
    </div>
  );
}

const StickyBox = { Root: StickyBoxRoot, Item: StickyBoxItem };

export {
  StickyBox,
  type StickyBoxItemHandle,
  type StickyBoxItemProps,
  type StickyBoxRootProps,
  type StickyEdge,
};
