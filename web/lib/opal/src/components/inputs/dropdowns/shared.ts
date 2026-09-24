import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  useFloating,
  autoUpdate,
  flip,
  offset,
  shift,
  size,
} from "@floating-ui/react-dom";
import { useClickOutside } from "@opal/hooks/useClickOutside";
import { SelectOption, SelectOptions } from "./types";

// =============================================================================
// Group helpers
// =============================================================================

/**
 * The listbox's render unit: a run of rows. Internal: callers write
 * `SelectOptions`, where loose options sit beside dividers; each divider is
 * a group and each run of loose options between them is one too. A
 * separator line renders between consecutive groups, titled when the group
 * below it has a title.
 */
export interface OptionGroup {
  title?: string;
  options: SelectOption[];
}

/** Groups the set for rendering: each divider is a group, each run of loose options one too. */
export function normalizeSections(options: SelectOptions = []): OptionGroup[] {
  const groups: OptionGroup[] = [];
  let looseRun: OptionGroup | null = null;
  for (const entry of options) {
    if ("options" in entry) {
      groups.push({ title: entry.title, options: entry.options });
      looseRun = null;
      continue;
    }
    if (looseRun) {
      looseRun.options.push(entry);
    } else {
      looseRun = { options: [entry] };
      groups.push(looseRun);
    }
  }
  return groups;
}

/** Flat option list in render order. */
export function flattenSections(groups: OptionGroup[]): SelectOption[] {
  return groups.flatMap((group) => group.options);
}

/**
 * Filters each group's options by the search term; groups left empty
 * disappear, so the dropdown's dividers never dangle.
 */
export function filterSections(
  groups: OptionGroup[],
  inputValue: string
): OptionGroup[] {
  const searchTerm = inputValue.trim().toLowerCase();
  if (!searchTerm) return groups.filter((g) => g.options.length > 0);
  return groups
    .map((group) => ({
      ...group,
      options: group.options.filter(
        (option) =>
          option.title.toLowerCase().includes(searchTerm) ||
          option.value.toLowerCase().includes(searchTerm)
      ),
    }))
    .filter((group) => group.options.length > 0);
}

// =============================================================================
// HOOK: useSelectKeyboard
// =============================================================================

interface UseSelectKeyboardProps {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  highlightedIndex: number;
  setHighlightedIndex: (index: number | ((prev: number) => number)) => void;
  setIsKeyboardNav: (isKeyboard: boolean) => void;
  allVisibleOptions: SelectOption[];
  onSelect: (option: SelectOption) => void;
}

/**
 * Manages keyboard navigation for the ComboBox
 * Handles arrow keys, Enter, Escape, and Tab
 */
export function useSelectKeyboard({
  isOpen,
  setIsOpen,
  highlightedIndex,
  setHighlightedIndex,
  setIsKeyboardNav,
  allVisibleOptions,
  onSelect,
}: UseSelectKeyboardProps) {
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLElement>) => {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setIsKeyboardNav(true); // Mark as keyboard navigation
          if (!isOpen) {
            setIsOpen(true);
            setHighlightedIndex(0);
          } else {
            setHighlightedIndex((prev) => {
              // If no item highlighted yet (-1), start at 0
              if (prev === -1) return 0;
              // Otherwise move down if not at end
              return prev < allVisibleOptions.length - 1 ? prev + 1 : prev;
            });
          }
          break;
        case "ArrowUp":
          e.preventDefault();
          setIsKeyboardNav(true); // Mark as keyboard navigation
          if (isOpen) {
            setHighlightedIndex((prev) => {
              // If at first item or no highlight, don't go further up
              if (prev <= 0) return -1;
              return prev - 1;
            });
          }
          break;
        case "Enter":
          // Always prevent default and stop propagation when dropdown is open
          // to avoid bubbling to parent forms
          if (isOpen) {
            e.preventDefault();
            e.stopPropagation();
            if (highlightedIndex >= 0) {
              const option = allVisibleOptions[highlightedIndex];
              if (option) {
                onSelect(option);
              }
            }
          }
          break;
        case "Escape":
          e.preventDefault();
          setIsOpen(false);
          setIsKeyboardNav(false);
          break;
        case "Tab":
          setIsOpen(false);
          setIsKeyboardNav(false);
          break;
      }
    },
    [
      isOpen,
      allVisibleOptions,
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
// HOOK: useSelectOverlay
// =============================================================================

interface UseSelectOverlayProps {
  isOpen: boolean;
  setIsOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

/**
 * Everything the family's dropdown overlay shares between the single and
 * multi selects: open/highlight/keyboard-nav state with its close-reset,
 * the floating-ui positioning (trigger-width, flip/shift), the refs, and
 * outside-click dismissal scoped to the whole trigger root plus the portal.
 *
 * Selection semantics (what a pick means) stay in the components.
 */
export function useSelectOverlay() {
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isKeyboardNav, setIsKeyboardNav] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Reset highlight and keyboard nav when closing
  useEffect(() => {
    if (!isOpen) {
      setHighlightedIndex(-1);
      setIsKeyboardNav(false);
    }
  }, [isOpen]);

  const { refs, floatingStyles } = useFloating({
    open: isOpen,
    placement: "bottom-start",
    middleware: [
      // 4px wider on each side than the trigger, shifted start-ward by 4px:
      // with the dropdown's 4px inset, the rows' bounding boxes then align
      // flush with the trigger's edges. crossAxis is direction-aware, so
      // RTL mirrors correctly.
      offset({ mainAxis: 4, crossAxis: -4 }),
      flip(),
      shift({ padding: 8 }),
      size({
        apply({ rects, elements }) {
          Object.assign(elements.floating.style, {
            width: `${rects.reference.width + 8}px`,
          });
        },
      }),
    ],
    whileElementsMounted: autoUpdate,
  });

  // The trigger root doubles as the floating reference.
  const setRootRef = useCallback(
    (node: HTMLDivElement | null) => {
      rootRef.current = node;
      refs.setReference(node);
    },
    [refs]
  );

  useClickOutside<HTMLElement>(
    [
      rootRef as React.RefObject<HTMLElement>,
      dropdownRef as React.RefObject<HTMLElement>,
    ],
    useCallback(() => {
      setIsOpen(false);
      setIsKeyboardNav(false);
    }, []),
    isOpen
  );

  return {
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    isKeyboardNav,
    setIsKeyboardNav,
    rootRef,
    setRootRef,
    inputRef,
    dropdownRef,
    setFloatingRef: refs.setFloating,
    floatingStyles,
  };
}
