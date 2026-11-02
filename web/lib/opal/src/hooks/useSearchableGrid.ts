"use client";

import { useCallback, useRef } from "react";
import useFocusOnMount from "@opal/hooks/useFocusOnMount";
import useGridNavigation from "@opal/hooks/useGridNavigation";
import useHotkey from "@opal/hooks/useHotkey";

export interface UseSearchableGridOptions {
  /** The search field's text, as typed (not deferred). */
  query: string;
  setQuery: (query: string) => void;
  /** Selects the grid's focusable items, in reading order. */
  itemSelector: string;
}

export interface UseSearchableGridReturn {
  /** Callback ref for the search field. It takes focus once it mounts. */
  inputRef: (input: HTMLInputElement | null) => void;
  /** The search field's key handler. */
  onSearchKeyDown: (event: React.KeyboardEvent<HTMLInputElement>) => void;
  /** Callback ref for the element that holds the items. */
  gridRef: (element: HTMLElement | null) => void;
  /**
   * Moves focus to the search field, with the caret at the end. A query
   * passed in replaces the current one.
   */
  focusSearch: (nextQuery?: string) => void;
}

/**
 * A search field over a grid of focusable items, such as a catalog of cards,
 * driven by the keyboard:
 *
 * - The field takes focus when it mounts, and on "/" from anywhere.
 * - In the field, Enter or ArrowDown moves to the first item. Escape clears
 *   the query, then, on an empty field, leaves it.
 * - In the grid, the arrows move between items. Leaving the top row, Escape,
 *   or typing returns to the field, typed characters included.
 */
export default function useSearchableGrid({
  query,
  setQuery,
  itemSelector,
}: UseSearchableGridOptions): UseSearchableGridReturn {
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const focusOnMount = useFocusOnMount<HTMLInputElement>();
  const inputRef = useCallback(
    (input: HTMLInputElement | null) => {
      searchInputRef.current = input;
      focusOnMount(input);
    },
    [focusOnMount]
  );

  function focusSearch(nextQuery?: string) {
    const input = searchInputRef.current;
    if (!input) return;
    if (nextQuery !== undefined) setQuery(nextQuery);
    input.focus();
    // After React writes the new value.
    requestAnimationFrame(() => {
      const end = input.value.length;
      input.setSelectionRange(end, end);
    });
  }

  useHotkey("/", () => focusSearch());

  // "/" is left to the hotkey above.
  const { ref: gridRef, focusFirst } = useGridNavigation({
    itemSelector,
    onExit: (direction) => {
      if (direction === "up") focusSearch();
    },
    onEscape: () => focusSearch(),
    onTypeAhead: (character) => {
      if (character === "/") return false;
      focusSearch(query + character);
    },
  });

  function onSearchKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    // Keys that build or cancel an IME composition belong to the IME.
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Escape") {
      event.preventDefault();
      if (query !== "") setQuery("");
      else event.currentTarget.blur();
      return;
    }
    if ((event.key === "Enter" || event.key === "ArrowDown") && focusFirst()) {
      event.preventDefault();
    }
  }

  return { inputRef, onSearchKeyDown, gridRef, focusSearch };
}
