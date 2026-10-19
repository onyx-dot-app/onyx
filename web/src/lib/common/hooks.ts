"use client";

import { useRef, type KeyboardEvent, type RefObject } from "react";
import { useGridNavigation } from "@opal/hooks";
import type { SearchFieldHandle } from "@/lib/common/components";

export interface UseSearchResultsNavigationOptions {
  /** The search field's current text, which type-ahead appends to. */
  query: string;
  /** Selects the focusable results inside the results container. */
  itemSelector: string;
}

/** Spread on the `SearchField`. */
export interface SearchNavigationProps {
  ref: RefObject<SearchFieldHandle | null>;
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
}

/** Spread on another control above the results, such as filter tabs. */
export interface EntryNavigationProps {
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
}

/** Spread on the element that holds the results. */
export interface ResultsNavigationProps {
  ref: (element: HTMLElement | null) => void;
}

export interface UseSearchResultsNavigationReturn {
  searchProps: SearchNavigationProps;
  entryProps: EntryNavigationProps;
  resultsProps: ResultsNavigationProps;
}

/**
 * Keyboard movement between a page's `SearchField` and its results. A page
 * only spreads the returned props; it holds no key logic of its own.
 *
 * - ArrowDown in the field (its × button too) or on an entry control, or
 *   Enter in the text, moves to the first result. Enter on the × clears, and
 *   Enter on an entry control is left to it.
 * - Arrows move between results (see `useGridNavigation`).
 * - ArrowUp from the top row, Escape, or typing on a result returns to the
 *   field; typed characters are added to the query. "/" is left to the
 *   field's hotkey.
 *
 * @example
 * ```tsx
 * const nav = useSearchResultsNavigation({ query, itemSelector: "[data-card]" });
 * <SearchField {...nav.searchProps} value={query} onChange={setQuery} />
 * <Tabs.List {...nav.entryProps}>{tabs}</Tabs.List>
 * <div {...nav.resultsProps}>{cards}</div>
 * ```
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

  function onSearchKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.nativeEvent.isComposing) return;
    const inText = event.target instanceof HTMLInputElement;
    if (
      (event.key === "ArrowDown" || (event.key === "Enter" && inText)) &&
      focusFirst()
    ) {
      event.preventDefault();
    }
  }

  function onEntryKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.defaultPrevented || event.nativeEvent.isComposing) return;
    if (event.key === "ArrowDown" && focusFirst()) event.preventDefault();
  }

  return {
    searchProps: { ref: searchRef, onKeyDown: onSearchKeyDown },
    entryProps: { onKeyDown: onEntryKeyDown },
    resultsProps: { ref: resultsRef },
  };
}
