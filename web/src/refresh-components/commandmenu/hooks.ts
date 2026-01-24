import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import type { CommandMenuEntry, CommandMenuGroup } from "./types";

// =============================================================================
// HOOK: useCommandMenuState
// =============================================================================

/**
 * Manages the internal state of the CommandMenu component
 * Simplified from useComboBoxState for modal menu use case
 */
export function useCommandMenuState() {
  const [isOpen, setIsOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isKeyboardNav, setIsKeyboardNav] = useState(false);

  // Reset state when closing
  useEffect(() => {
    if (!isOpen) {
      setHighlightedIndex(-1);
      setIsKeyboardNav(false);
      setSearchValue("");
    }
  }, [isOpen]);

  return {
    isOpen,
    setIsOpen,
    searchValue,
    setSearchValue,
    highlightedIndex,
    setHighlightedIndex,
    isKeyboardNav,
    setIsKeyboardNav,
  };
}

// =============================================================================
// HOOK: useCommandMenuKeyboard
// =============================================================================

interface UseCommandMenuKeyboardProps {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  highlightedIndex: number;
  setHighlightedIndex: (index: number | ((prev: number) => number)) => void;
  setIsKeyboardNav: (isKeyboard: boolean) => void;
  itemCount: number;
  onSelect: (index: number) => void;
}

/**
 * Manages keyboard navigation for the CommandMenu
 * Adapted from useComboBoxKeyboard - handles arrow keys, Enter, Escape
 */
export function useCommandMenuKeyboard({
  isOpen,
  setIsOpen,
  highlightedIndex,
  setHighlightedIndex,
  setIsKeyboardNav,
  itemCount,
  onSelect,
}: UseCommandMenuKeyboardProps) {
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!itemCount) return;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setIsKeyboardNav(true);
          if (!isOpen) {
            setIsOpen(true);
            setHighlightedIndex(0);
          } else {
            setHighlightedIndex((prev) => {
              if (prev === -1) return 0;
              return prev < itemCount - 1 ? prev + 1 : prev;
            });
          }
          break;
        case "ArrowUp":
          e.preventDefault();
          setIsKeyboardNav(true);
          if (isOpen) {
            setHighlightedIndex((prev) =>
              prev <= 0 ? itemCount - 1 : prev - 1
            );
          }
          break;
        case "Enter":
          if (isOpen && highlightedIndex >= 0) {
            e.preventDefault();
            e.stopPropagation();
            onSelect(highlightedIndex);
            setIsOpen(false);
          }
          break;
        case "Escape":
          e.preventDefault();
          setIsOpen(false);
          break;
      }
    },
    [
      isOpen,
      itemCount,
      highlightedIndex,
      onSelect,
      setIsOpen,
      setHighlightedIndex,
      setIsKeyboardNav,
    ]
  );

  return { handleKeyDown };
}

// =============================================================================
// HOOK: useCommandMenuFilter
// =============================================================================

export interface CommandMenuFilterItem {
  label: string;
  description?: string;
  [key: string]: unknown;
}

interface UseCommandMenuFilterProps<T extends CommandMenuFilterItem> {
  items: T[];
  searchValue: string;
}

/**
 * Filters items based on search value
 * Adapted from useOptionFiltering
 */
export function useCommandMenuFilter<T extends CommandMenuFilterItem>({
  items,
  searchValue,
}: UseCommandMenuFilterProps<T>): T[] {
  return useMemo(() => {
    if (!searchValue.trim()) return items;
    const term = searchValue.toLowerCase();
    return items.filter(
      (item) =>
        item.label.toLowerCase().includes(term) ||
        item.description?.toLowerCase().includes(term)
    );
  }, [items, searchValue]);
}

// =============================================================================
// HOOK: useCommandMenuGroupFilter
// =============================================================================

interface UseCommandMenuGroupFilterProps {
  groups: CommandMenuGroup[];
  searchValue: string;
}

/**
 * Filters groups and their items based on search value
 * Preserves group structure but filters out empty groups
 */
export function useCommandMenuGroupFilter({
  groups,
  searchValue,
}: UseCommandMenuGroupFilterProps): CommandMenuGroup[] {
  return useMemo(() => {
    if (!searchValue.trim()) return groups;
    const term = searchValue.toLowerCase();

    return groups
      .map((group) => ({
        ...group,
        items: group.items.filter(
          (item) =>
            item.label.toLowerCase().includes(term) ||
            item.description?.toLowerCase().includes(term)
        ),
      }))
      .filter((group) => group.items.length > 0);
  }, [groups, searchValue]);
}

// =============================================================================
// HOOK: useCommandMenuEntryFilter
// =============================================================================

interface UseCommandMenuEntryFilterProps<T extends CommandMenuEntry> {
  items: T[];
  searchValue: string;
}

/**
 * Filters CommandMenuEntry items based on search value
 * Works with the discriminated union types (filter, item, action)
 */
export function useCommandMenuEntryFilter<T extends CommandMenuEntry>({
  items,
  searchValue,
}: UseCommandMenuEntryFilterProps<T>): T[] {
  return useMemo(() => {
    if (!searchValue.trim()) return items;
    const term = searchValue.toLowerCase();
    return items.filter(
      (item) =>
        item.label.toLowerCase().includes(term) ||
        item.description?.toLowerCase().includes(term)
    );
  }, [items, searchValue]);
}

// =============================================================================
// HOOK: useItemRegistry
// =============================================================================

/**
 * Manages item registration for keyboard navigation
 * Items register themselves when mounting and unregister when unmounting
 */
export function useItemRegistry() {
  const itemsRef = useRef<string[]>([]);
  const [itemCount, setItemCount] = useState(0);

  const registerItem = useCallback((value: string) => {
    if (!itemsRef.current.includes(value)) {
      itemsRef.current.push(value);
      setItemCount(itemsRef.current.length);
    }
    return itemsRef.current.indexOf(value);
  }, []);

  const unregisterItem = useCallback((value: string) => {
    const index = itemsRef.current.indexOf(value);
    if (index !== -1) {
      itemsRef.current.splice(index, 1);
      setItemCount(itemsRef.current.length);
    }
  }, []);

  const getItemIndex = useCallback((value: string) => {
    return itemsRef.current.indexOf(value);
  }, []);

  const getItemByIndex = useCallback((index: number) => {
    return itemsRef.current[index];
  }, []);

  const resetItems = useCallback(() => {
    itemsRef.current = [];
    setItemCount(0);
  }, []);

  return {
    registerItem,
    unregisterItem,
    getItemIndex,
    getItemByIndex,
    itemCount,
    resetItems,
  };
}
