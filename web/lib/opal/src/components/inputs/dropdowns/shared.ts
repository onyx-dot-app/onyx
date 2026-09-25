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
  /** A search is on: groups open to show their matches, until folded. */
  searching: boolean;
}

/**
 * Fold state for foldable groups, per open session. A group starts closed
 * unless it holds the selection, and starts open while a search is on;
 * either way a click on its title toggles it, and the toggle holds until
 * the search starts or stops, or the list closes. Returns the groups with
 * folded rows withheld, so rendering and the keyboard order agree.
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
  // Toggles reset when the list closes and when a search starts or stops,
  // so each of those begins from the defaults below.
  useEffect(() => {
    setToggled(new Map());
  }, [isOpen, searching]);

  const isGroupOpen = useCallback(
    (group: OptionGroup) => {
      if (!group.foldable || group.title === undefined) return true;
      const choice = toggled.get(group.title);
      if (choice !== undefined) return choice;
      if (searching) return true;
      return group.options.some(isSelected);
    },
    [toggled, searching, isSelected]
  );

  const toggleGroup = useCallback(
    (group: OptionGroup) => {
      if (group.title === undefined) return;
      const title = group.title;
      const open = isGroupOpen(group);
      setToggled((prev) => new Map(prev).set(title, !open));
    },
    [isGroupOpen]
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
}

/**
 * Keyboard navigation for the family's listbox, the same for every trigger:
 * Enter or ArrowDown opens a closed list; open, the arrows and Tab walk the
 * stops and wrap around from the last row to the first, Enter picks the
 * highlighted row or toggles the highlighted title, and Escape closes. A
 * closed list leaves Tab alone, so it moves on as normal. Physical focus
 * stays on the trigger or the search field; the highlight moves and
 * `aria-activedescendant` follows it.
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
}: UseSelectKeyboardProps) {
  const count = items.length;

  // A disabled row is not a stop: the walk passes over it.
  const isStop = useCallback(
    (index: number) => {
      const item = items[index];
      return (
        item !== undefined && !(item.kind === "option" && item.option.disabled)
      );
    },
    [items]
  );

  // The stop after `prev`, wrapping from the last row to the first; from
  // nothing highlighted (-1) both directions enter the list.
  const next = useCallback(
    (prev: number) => {
      let index = prev;
      for (let step = 0; step < count; step++) {
        index = index < count - 1 ? index + 1 : 0;
        if (isStop(index)) return index;
      }
      return -1;
    },
    [count, isStop]
  );
  const previous = useCallback(
    (prev: number) => {
      let index = prev;
      for (let step = 0; step < count; step++) {
        index = index > 0 ? index - 1 : count - 1;
        if (isStop(index)) return index;
      }
      return -1;
    },
    [count, isStop]
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
            // Opening lands on the first row.
            setIsOpen(true);
            setHighlightedIndex(0);
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
          // Inside the list Tab walks the stops, both ways, wrapping.
          e.preventDefault();
          setIsKeyboardNav(true);
          setHighlightedIndex(e.shiftKey ? previous : next);
          break;
        case "Enter":
          if (!isOpen) {
            e.preventDefault();
            setIsOpen(true);
            setHighlightedIndex(-1);
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
  // A wrapping <label> is part of the trigger's hit area: the browser
  // forwards its clicks to the input, so it must not count as outside.
  const labelRef = useRef<HTMLLabelElement>(null);
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
      labelRef.current = node?.closest("label") ?? null;
      refs.setReference(node);
    },
    [refs]
  );

  // Otherwise a label click dismisses the list and the forwarded click
  // reopens it, so a second click on the label never closes it.
  useClickOutside<HTMLElement>(
    [
      rootRef as React.RefObject<HTMLElement>,
      labelRef as React.RefObject<HTMLElement>,
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
