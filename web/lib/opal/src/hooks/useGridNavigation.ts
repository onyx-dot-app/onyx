"use client";

import "@opal/hooks/useGridNavigation.css";
import { useCallback, useEffect, useRef, useState } from "react";

export type GridDirection = "up" | "down" | "left" | "right";

export interface UseGridNavigationOptions {
  /** Selects the focusable items inside the container, in reading order. */
  itemSelector: string;
  /** Whether the keys are handled. @default true */
  enabled?: boolean;
  /** An arrow key found no item that way, e.g. ArrowUp on the top row. */
  onExit?: (direction: GridDirection, from: HTMLElement) => void;
  /** Escape was pressed on an item. */
  onEscape?: (from: HTMLElement) => void;
  /**
   * A printable character (not Space, which activates the item) was typed
   * on an item. Return `false` to leave the key unhandled, so a page-wide
   * hotkey can take it.
   */
  onTypeAhead?: (character: string, from: HTMLElement) => boolean | void;
}

export interface UseGridNavigationReturn {
  /**
   * Put on the container. A callback ref, so a container that mounts late,
   * or is replaced, still gets the keys.
   */
  ref: (element: HTMLElement | null) => void;
  /** Focuses the first item. Returns false when there is none. */
  focusFirst: () => boolean;
}

/**
 * Which input last drove the container: `"keyboard"` or `"pointer"`, unset
 * until one does. Read by this hook's stylesheet and by Interactive's.
 */
const NAV_MODE_ATTRIBUTE = "data-opal-nav-mode";

type NavMode = "keyboard" | "pointer";

const DIRECTIONS: Record<string, GridDirection> = {
  ArrowUp: "up",
  ArrowDown: "down",
  ArrowLeft: "left",
  ArrowRight: "right",
};

/** Rows are compared with a pixel of slack for sub-pixel layout. */
function sameRow(a: DOMRect, b: DOMRect): boolean {
  return Math.abs(a.top - b.top) < 1;
}

/**
 * The item an arrow key lands on, or null when there is none that way. It
 * reads the layout rather than indexes, so it follows a responsive column
 * count, a right-to-left layout, and crosses between grids in the same
 * container. Left and right take the nearest item in the row; up and down
 * take the nearest row and the item closest to the same column.
 */
function itemInDirection(
  items: HTMLElement[],
  from: HTMLElement,
  direction: GridDirection
): HTMLElement | null {
  const origin = from.getBoundingClientRect();

  // Left and right read positions too, not list order, so a right-to-left
  // layout moves the way the arrow points.
  if (direction === "left" || direction === "right") {
    const toLeft = direction === "left";
    return (
      items.reduce<{ item: HTMLElement; gap: number } | null>(
        (nearest, item) => {
          const rect = item.getBoundingClientRect();
          if (item === from || !sameRow(rect, origin)) return nearest;
          const gap = toLeft
            ? origin.left - rect.left
            : rect.left - origin.left;
          if (gap <= 0 || (nearest && nearest.gap <= gap)) return nearest;
          return { item, gap };
        },
        null
      )?.item ?? null
    );
  }

  const below = direction === "down";
  const candidates = items
    .map((item) => ({ item, rect: item.getBoundingClientRect() }))
    .filter(({ rect }) =>
      below ? rect.top > origin.top + 1 : rect.top < origin.top - 1
    );
  if (candidates.length === 0) return null;

  const tops = candidates.map(({ rect }) => rect.top);
  const rowTop = below ? Math.min(...tops) : Math.max(...tops);
  const centerX = origin.left + origin.width / 2;
  const distance = (rect: DOMRect) =>
    Math.abs(rect.left + rect.width / 2 - centerX);

  return candidates
    .filter(({ rect }) => Math.abs(rect.top - rowTop) < 1)
    .reduce((best, candidate) =>
      distance(candidate.rect) < distance(best.rect) ? candidate : best
    ).item;
}

/**
 * Arrow-key navigation over a grid of focusable items, such as a catalog of
 * cards. Each item keeps its own Tab stop; the arrows add 2D movement.
 *
 * The movement reads where items sit on screen, so it follows a responsive
 * column count and continues across several grids (e.g. sections) inside
 * the one container. Keys pressed on a nested control inside an item, and
 * keys with Ctrl, ⌘ or Alt held, are left alone.
 *
 * Only the input in use highlights an item, never both:
 * - Keyboard mode (Tab or an arrow moved focus): the contents ignore the
 *   pointer, so a resting pointer's hover does not paint a second item.
 * - Pointer mode (the pointer moved): the focused item keeps focus, so Tab
 *   resumes from it, but Interactive does not paint its focus.
 * Focus leaving the container clears the mode.
 *
 * @example
 * ```tsx
 * const { ref, focusFirst } = useGridNavigation({
 *   itemSelector: "[data-card]",
 *   onExit: (direction) => direction === "up" && searchRef.current?.focus(),
 *   onEscape: () => searchRef.current?.focus(),
 * });
 *
 * <input ref={searchRef} onKeyDown={(e) => e.key === "ArrowDown" && focusFirst()} />
 * <div ref={ref}>{cards}</div>
 * ```
 */
export default function useGridNavigation(
  options: UseGridNavigationOptions
): UseGridNavigationReturn {
  // State rather than a ref object, so mounting the container re-runs the
  // effect that binds it.
  const [container, setContainer] = useState<HTMLElement | null>(null);

  // The latest options, so inline callbacks do not rebind the listener.
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  });

  const { itemSelector, enabled = true } = options;

  const items = useCallback(
    () =>
      Array.from(container?.querySelectorAll<HTMLElement>(itemSelector) ?? []),
    [container, itemSelector]
  );

  useEffect(() => {
    if (!enabled || !container) return;

    function handleKeyDown(event: KeyboardEvent) {
      const item = event.target;
      if (!(item instanceof HTMLElement) || !item.matches(itemSelector)) {
        return;
      }
      if (event.defaultPrevented) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const { onExit, onEscape, onTypeAhead } = optionsRef.current;

      const direction = DIRECTIONS[event.key];
      if (direction) {
        event.preventDefault();
        setMode("keyboard");
        const next = itemInDirection(items(), item, direction);
        if (next) next.focus();
        else onExit?.(direction, item);
        return;
      }

      if (event.key === "Escape" && onEscape) {
        event.preventDefault();
        onEscape(item);
        return;
      }

      if (event.key.length === 1 && event.key !== " " && onTypeAhead) {
        if (onTypeAhead(event.key, item) !== false) event.preventDefault();
      }
    }

    function setMode(mode: NavMode | null) {
      if (mode === null) container?.removeAttribute(NAV_MODE_ATTRIBUTE);
      else if (container?.getAttribute(NAV_MODE_ATTRIBUTE) !== mode) {
        container?.setAttribute(NAV_MODE_ATTRIBUTE, mode);
      }
    }

    // `:focus-visible` is the browser's own test for focus the keyboard
    // brought, so Tab and the arrows enter keyboard mode and a click does
    // not.
    function handleFocusIn(event: FocusEvent) {
      const item = event.target;
      if (
        item instanceof HTMLElement &&
        item.matches(itemSelector) &&
        item.matches(":focus-visible")
      ) {
        setMode("keyboard");
      }
    }

    function handleFocusOut(event: FocusEvent) {
      const next = event.relatedTarget;
      if (!(next instanceof Node) || !container?.contains(next)) {
        setMode(null);
      }
    }

    function handlePointerMove() {
      setMode("pointer");
    }

    container.addEventListener("keydown", handleKeyDown);
    container.addEventListener("focusin", handleFocusIn);
    container.addEventListener("focusout", handleFocusOut);
    container.addEventListener("pointermove", handlePointerMove);
    return () => {
      container.removeEventListener("keydown", handleKeyDown);
      container.removeEventListener("focusin", handleFocusIn);
      container.removeEventListener("focusout", handleFocusOut);
      container.removeEventListener("pointermove", handlePointerMove);
      setMode(null);
    };
  }, [container, itemSelector, enabled, items]);

  const focusFirst = useCallback(() => {
    const [first] = items();
    first?.focus();
    return first !== undefined;
  }, [items]);

  return { ref: setContainer, focusFirst };
}
