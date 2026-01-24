import { useState, useEffect, useMemo } from "react";
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

  // Reset search when closing
  useEffect(() => {
    if (!isOpen) {
      setSearchValue("");
    }
  }, [isOpen]);

  return {
    isOpen,
    setIsOpen,
    searchValue,
    setSearchValue,
  };
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
