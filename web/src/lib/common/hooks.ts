"use client";

import { useRef, type KeyboardEvent } from "react";
import { useGridNavigation } from "@opal/hooks";
import type { SearchFieldHandle } from "@/lib/common/components";

export interface UseSearchResultsNavigationOptions {
  /** The search field's current text, which type-ahead appends to. */
  query: string;
  /** Selects the focusable results inside the results container. */
  itemSelector: string;
}

export interface UseSearchResultsNavigationReturn {
  /** Put on the `SearchField`. */
  searchRef: React.RefObject<SearchFieldHandle | null>;
  /** Put on the `SearchField` as `onKeyDown`. */
  onSearchKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
  /**
   * Put as `onKeyDown` on other controls above the results, such as filter
   * tabs: ArrowDown moves to the first result. Enter is left to the control.
   */
  onEntryKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
  /** Put on the element that holds the results. */
  resultsRef: (element: HTMLElement | null) => void;
}

/**
 * Keyboard movement between a page's `SearchField` and its results.
 *
 * - ArrowDown or Enter in the field, or ArrowDown on another control above
 *   the results (`onEntryKeyDown`), moves to the first result.
 * - Arrows move between results (see `useGridNavigation`).
 * - ArrowUp from the top row, Escape, or typing on a result returns to the
 *   field; typed characters are added to the query. "/" is left to the
 *   field's hotkey.
 */
export function useSearchResultsNavigation({
  query,
  itemSelector,
}: UseSearchResultsNavigationOptions): UseSearchResultsNavigationReturn {
  const searchRef = useRef<SearchFieldHandle>(null);

  const { ref: resultsRef, focusFirst } = useGridNavigation({
    itemSelector,
    onExit: (direction) => {
      if (direction === "up") searchRef.current?.focus();
    },
    onEscape: () => searchRef.current?.focus(),
    onTypeAhead: (character) => {
      if (character === "/") return false;
      searchRef.current?.focus(query + character);
    },
  });

  function onSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return;
    if ((event.key === "Enter" || event.key === "ArrowDown") && focusFirst()) {
      event.preventDefault();
    }
  }

  function onEntryKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.defaultPrevented || event.nativeEvent.isComposing) return;
    if (event.key === "ArrowDown" && focusFirst()) event.preventDefault();
  }

  return { searchRef, onSearchKeyDown, onEntryKeyDown, resultsRef };
}
