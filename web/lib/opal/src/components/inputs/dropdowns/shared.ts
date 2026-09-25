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
  /** The rows fold behind the title (see `SelectDivider`). */
  foldable?: boolean;
  /** Render-only: the group is folded, so its rows are withheld. */
  folded?: boolean;
}

/** Groups the set for rendering: each divider is a group, each run of loose options one too. */
export function normalizeSections(options: SelectOptions = []): OptionGroup[] {
  const groups: OptionGroup[] = [];
  let looseRun: OptionGroup | null = null;
  for (const entry of options) {
    if ("options" in entry) {
      groups.push({
        title: entry.title,
        options: entry.options,
        foldable: entry.foldable,
      });
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
 * What the keyboard walks: a foldable group's title is a stop of its own
 * (Enter toggles it), then its rows. The list renders in this exact order,
 * so `highlightedIndex` addresses the same stop in both.
 */
export type NavItem =
  | { kind: "group"; group: OptionGroup }
  | { kind: "option"; option: SelectOption };

export function buildNavItems(
  groups: OptionGroup[],
  createOption?: SelectOption
): NavItem[] {
  const items: NavItem[] = [];
  if (createOption) items.push({ kind: "option", option: createOption });
  for (const group of groups) {
    if (group.foldable && group.title !== undefined) {
      items.push({ kind: "group", group });
    }
    for (const option of group.options) items.push({ kind: "option", option });
  }
  return items;
}

/**
 * Filters each group's options by the search term, matched against a
 * row's title or value. A term that matches a divider's title keeps the
 * whole section. Groups left empty disappear, so the dropdown's dividers
 * never dangle.
 */
export function filterSections(
  groups: OptionGroup[],
  inputValue: string
): OptionGroup[] {
  const searchTerm = inputValue.trim().toLowerCase();
  if (!searchTerm) return groups.filter((g) => g.options.length > 0);
  return groups
    .map((group) =>
      group.title?.toLowerCase().includes(searchTerm)
        ? group
        : {
            ...group,
            options: group.options.filter(
              (option) =>
                option.title.toLowerCase().includes(searchTerm) ||
                option.value.toLowerCase().includes(searchTerm)
            ),
          }
    )
    .filter((group) => group.options.length > 0);
}

// =============================================================================
// HOOK: useFoldedGroups
// =============================================================================

interface UseFoldedGroupsProps {
  isOpen: boolean;
  /** Post-filter groups in render order. */
  sections: OptionGroup[];
  isSelected: (option: SelectOption) => boolean;
  /** A search is on: every group shows its matches and folding is off. */
  searching: boolean;
}

/**
 * Fold state for foldable groups, per open session. A group opens when it
 * holds the selection or while searching; otherwise it starts closed, and
 * a click on its title toggles it until the list closes. Returns the
 * groups with folded rows withheld, so rendering and the keyboard order
 * agree.
 */
export function useFoldedGroups({
  isOpen,
  sections,
  isSelected,
  searching,
}: UseFoldedGroupsProps) {
  const [toggled, setToggled] = useState<ReadonlyMap<string, boolean>>(
    new Map()
  );
  useEffect(() => {
    if (!isOpen) setToggled(new Map());
  }, [isOpen]);

  const isGroupOpen = useCallback(
    (group: OptionGroup) => {
      if (!group.foldable || group.title === undefined || searching) {
        return true;
      }
      const choice = toggled.get(group.title);
      if (choice !== undefined) return choice;
      return group.options.some(isSelected);
    },
    [toggled, searching, isSelected]
  );

  const toggleGroup = useCallback(
    (group: OptionGroup) => {
      if (searching || group.title === undefined) return;
      const title = group.title;
      const open = isGroupOpen(group);
      setToggled((prev) => new Map(prev).set(title, !open));
    },
    [searching, isGroupOpen]
  );

  const foldedSections = useMemo(
    () =>
      sections.map((group) =>
        isGroupOpen(group) ? group : { ...group, options: [], folded: true }
      ),
    [sections, isGroupOpen]
  );

  return { foldedSections, toggleGroup };
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
  /** The stops in render order. */
  items: NavItem[];
  onSelect: (option: SelectOption) => void;
  onToggleGroup?: (group: OptionGroup) => void;
  /**
   * A Select walks its list: Enter opens it, Tab and Shift+Tab move like
   * the arrows, and both wrap around; with a search field, that field is
   * the stop before the first row (index -1). A ComboBox keeps the text
   * field's own Tab, which closes the list and moves on.
   */
  mode: "select" | "combobox";
  /** A search field sits above the rows and is a stop in the cycle. */
  hasSearch?: boolean;
}

/**
 * Keyboard navigation for the family's listbox: arrows, Enter, Escape and
 * Tab. Physical focus stays on the trigger or the search field; the
 * highlight moves and `aria-activedescendant` follows it.
 */
export function useSelectKeyboard({
  isOpen,
  setIsOpen,
  highlightedIndex,
  setHighlightedIndex,
  setIsKeyboardNav,
  items,
  onSelect,
  onToggleGroup,
  mode,
  hasSearch = false,
}: UseSelectKeyboardProps) {
  const cycles = mode === "select";
  const count = items.length;

  // The stop after `prev`. A Select wraps: past the last row comes the
  // search field when there is one, else the first row.
  const next = useCallback(
    (prev: number) => {
      if (count === 0) return -1;
      if (prev < count - 1) return prev + 1;
      return cycles ? (hasSearch ? -1 : 0) : prev;
    },
    [count, cycles, hasSearch]
  );
  const previous = useCallback(
    (prev: number) => {
      if (count === 0) return -1;
      if (prev > 0) return prev - 1;
      if (prev === 0) return cycles && !hasSearch ? count - 1 : -1;
      // Nothing highlighted (the search field, when there is one).
      return cycles ? count - 1 : -1;
    },
    [count, cycles, hasSearch]
  );

  const activate = useCallback(() => {
    const item = items[highlightedIndex];
    if (!item) return;
    if (item.kind === "option") onSelect(item.option);
    else onToggleGroup?.(item.group);
  }, [items, highlightedIndex, onSelect, onToggleGroup]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLElement>) => {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setIsKeyboardNav(true);
          if (!isOpen) {
            // Opening lands on the first stop: the search field when there
            // is one, else the first row.
            setIsOpen(true);
            setHighlightedIndex(cycles && hasSearch ? -1 : 0);
          } else {
            setHighlightedIndex(next);
          }
          break;
        case "ArrowUp":
          e.preventDefault();
          setIsKeyboardNav(true);
          if (isOpen) setHighlightedIndex(previous);
          break;
        case "Tab":
          if (!isOpen) break;
          if (!cycles) {
            setIsOpen(false);
            setIsKeyboardNav(false);
            break;
          }
          // Inside the list Tab walks the stops, both ways, wrapping.
          e.preventDefault();
          setIsKeyboardNav(true);
          setHighlightedIndex(e.shiftKey ? previous : next);
          break;
        case "Enter":
          if (!isOpen) {
            if (cycles) {
              e.preventDefault();
              setIsOpen(true);
              setHighlightedIndex(-1);
            }
            break;
          }
          // Always prevent default and stop propagation when the list is
          // open, so the key never reaches an enclosing form.
          e.preventDefault();
          e.stopPropagation();
          activate();
          break;
        case "Escape":
          e.preventDefault();
          setIsOpen(false);
          setIsKeyboardNav(false);
          break;
      }
    },
    [
      isOpen,
      cycles,
      next,
      previous,
      activate,
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
