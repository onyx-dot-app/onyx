"use client";

import "@opal/hooks/useGridNavigation.css";
import { useCallback, useEffect, useRef, type RefObject } from "react";

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
  /** Focuses the first item. Returns false when there is none. */
  focusFirst: () => boolean;
}

/** Set on the container while the keyboard drives; see the stylesheet. */
const KEYBOARD_MODE_ATTRIBUTE = "data-opal-keyboard-nav";

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
 * count and crosses between grids in the same container. Left and right
 * stay in the row; up and down take the nearest row and the item closest
 * to the same column.
 */
function itemInDirection(
  items: HTMLElement[],
  from: HTMLElement,
  direction: GridDirection
): HTMLElement | null {
  const origin = from.getBoundingClientRect();

  if (direction === "left" || direction === "right") {
    const index = items.indexOf(from);
    const next = items[direction === "left" ? index - 1 : index + 1];
    return next && sameRow(next.getBoundingClientRect(), origin) ? next : null;
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
 * While the keyboard moves focus between items (Tab or the arrows), the
 * container is in keyboard mode: its contents ignore the pointer, so the
 * hover under a resting pointer does not highlight a second item beside
 * the focused one. Moving the pointer, or focus leaving the container,
 * ends it.
 *
 * @example
 * ```tsx
 * const gridRef = useRef<HTMLDivElement>(null);
 * const { focusFirst } = useGridNavigation(gridRef, {
 *   itemSelector: "[data-card]",
 *   onExit: (direction) => direction === "up" && searchRef.current?.focus(),
 *   onEscape: () => searchRef.current?.focus(),
 * });
 *
 * <input ref={searchRef} onKeyDown={(e) => e.key === "ArrowDown" && focusFirst()} />
 * <div ref={gridRef}>{cards}</div>
 * ```
 */
export default function useGridNavigation(
  containerRef: RefObject<HTMLElement | null>,
  options: UseGridNavigationOptions
): UseGridNavigationReturn {
  // The latest options, so inline callbacks do not rebind the listener.
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  });

  const { itemSelector, enabled = true } = options;

  const items = useCallback(
    () =>
      Array.from(
        containerRef.current?.querySelectorAll<HTMLElement>(itemSelector) ?? []
      ),
    [containerRef, itemSelector]
  );

  useEffect(() => {
    const container = containerRef.current;
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
        container?.setAttribute(KEYBOARD_MODE_ATTRIBUTE, "");
      }
    }

    function endKeyboardMode() {
      container?.removeAttribute(KEYBOARD_MODE_ATTRIBUTE);
    }

    function handleFocusOut(event: FocusEvent) {
      const next = event.relatedTarget;
      if (!(next instanceof Node) || !container?.contains(next)) {
        endKeyboardMode();
      }
    }

    container.addEventListener("keydown", handleKeyDown);
    container.addEventListener("focusin", handleFocusIn);
    container.addEventListener("focusout", handleFocusOut);
    container.addEventListener("pointermove", endKeyboardMode);
    return () => {
      container.removeEventListener("keydown", handleKeyDown);
      container.removeEventListener("focusin", handleFocusIn);
      container.removeEventListener("focusout", handleFocusOut);
      container.removeEventListener("pointermove", endKeyboardMode);
      endKeyboardMode();
    };
  }, [containerRef, itemSelector, enabled, items]);

  const focusFirst = useCallback(() => {
    const [first] = items();
    first?.focus();
    return first !== undefined;
  }, [items]);

  return { focusFirst };
}
