import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  autoUpdate,
  flip,
  offset,
  shift,
  size,
  useFloating,
} from "@floating-ui/react-dom";
import { useClickOutside } from "@opal/hooks/useClickOutside";
import type {
  DropdownOption,
  NavItem,
  OptionGroup,
} from "@opal/components/dropdown/types";

// =============================================================================
// HOOK: useFoldedGroups
// =============================================================================

interface UseFoldedGroupsProps {
  isOpen: boolean;
  /** Post-filter groups in render order. */
  groups: OptionGroup[];
  isSelected: (option: DropdownOption) => boolean;
  /** A search is on: groups open to show their matches, until folded. */
  searching: boolean;
}

/**
 * Fold state for foldable groups, per open session. A group starts closed
 * unless it holds the selection, and starts open while a search is on;
 * either way a click on its title toggles it. The selection those defaults
 * read is the one from when the session started (the list opened, or a
 * search started or stopped); after that only a title click changes a
 * group, so a pick or a deselection while the list is open never folds
 * anything, and a group that arrives mid-session starts as it would have at
 * the start. Returns the groups with folded rows withheld, so rendering and
 * the keyboard order agree.
 */
export function useFoldedGroups({
  isOpen,
  groups,
  isSelected,
  searching,
}: UseFoldedGroupsProps) {
  // The selection as the session found it. Held as state, not derived, so
  // the live selection cannot re-fold groups afterwards.
  const [sessionIsSelected, setSessionIsSelected] = useState(() => isSelected);
  const [toggled, setToggled] = useState<ReadonlyMap<string, boolean>>(
    new Map()
  );

  const latestIsSelected = useRef(isSelected);
  useEffect(() => {
    latestIsSelected.current = isSelected;
  });
  useEffect(() => {
    if (!isOpen) return;
    setSessionIsSelected(() => latestIsSelected.current);
    setToggled(new Map());
  }, [isOpen, searching]);

  const isGroupOpen = useCallback(
    (group: OptionGroup) => {
      if (!group.foldable || group.title === undefined) return true;
      const choice = toggled.get(group.title);
      if (choice !== undefined) return choice;
      return searching || group.options.some(sessionIsSelected);
    },
    [toggled, searching, sessionIsSelected]
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

  const foldedGroups = useMemo(
    () =>
      groups.map((group) =>
        isGroupOpen(group) ? group : { ...group, folded: true }
      ),
    [groups, isGroupOpen]
  );

  return { foldedGroups, toggleGroup };
}

// =============================================================================
// HOOK: useDropdownKeyboard
// =============================================================================

/**
 * What `Dropdown.Data` registers for the keyboard: the stops in render
 * order and what Enter does to each. Read through a ref at event time, so
 * the handler never goes stale and the list never re-renders the trigger.
 */
export interface ListModel {
  items: NavItem[];
  onSelect: (option: DropdownOption) => void;
  onToggleGroup: (group: OptionGroup) => void;
  onCreate: (text: string) => void;
}

interface UseDropdownKeyboardProps {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  highlightedIndex: number;
  setHighlightedIndex: (index: number | ((prev: number) => number)) => void;
  setIsKeyboardNav: (isKeyboard: boolean) => void;
  listRef: React.RefObject<ListModel>;
}

/**
 * Keyboard navigation for the list, the same for every trigger: Enter or
 * ArrowDown opens a closed list; open, the arrows and Tab walk the stops
 * and wrap around from the last row to the first, Enter picks the
 * highlighted row or toggles the highlighted title, and Escape closes. A
 * closed list leaves Tab alone, so it moves on as normal. Physical focus
 * stays on the trigger or the search field; the highlight moves and
 * `aria-activedescendant` follows it. A handler that ran before this one
 * and cancelled the event keeps the key.
 */
export function useDropdownKeyboard({
  isOpen,
  setIsOpen,
  highlightedIndex,
  setHighlightedIndex,
  setIsKeyboardNav,
  listRef,
}: UseDropdownKeyboardProps) {
  // A disabled row is not a stop: the walk passes over it.
  const isStop = useCallback(
    (index: number) => {
      const item = listRef.current.items[index];
      return (
        item !== undefined && !(item.kind === "option" && item.option.disabled)
      );
    },
    [listRef]
  );

  // The stop after `prev`, wrapping from the last row to the first; from
  // nothing highlighted (-1) both directions enter the list.
  const next = useCallback(
    (prev: number) => {
      const count = listRef.current.items.length;
      let index = prev;
      for (let step = 0; step < count; step++) {
        index = index < count - 1 ? index + 1 : 0;
        if (isStop(index)) return index;
      }
      return -1;
    },
    [listRef, isStop]
  );
  const previous = useCallback(
    (prev: number) => {
      const count = listRef.current.items.length;
      let index = prev;
      for (let step = 0; step < count; step++) {
        index = index > 0 ? index - 1 : count - 1;
        if (isStop(index)) return index;
      }
      return -1;
    },
    [listRef, isStop]
  );

  const activate = useCallback(() => {
    const { items, onSelect, onToggleGroup, onCreate } = listRef.current;
    const item = items[highlightedIndex];
    if (!item) return;
    if (item.kind === "option") onSelect(item.option);
    else if (item.kind === "create") onCreate(item.text);
    else onToggleGroup(item.group);
  }, [listRef, highlightedIndex]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLElement>) => {
      if (e.defaultPrevented) return;
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
// HOOK: useDropdownOverlay
// =============================================================================

interface UseDropdownOverlayProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/**
 * Everything the overlay shares across triggers: open, highlight and
 * keyboard-nav state with their close-reset, the floating-ui positioning
 * (reference width, flip and shift), the refs, and outside-click dismissal
 * scoped to the reference element, its label and the portal.
 */
export function useDropdownOverlay({
  open: openProp,
  onOpenChange,
}: UseDropdownOverlayProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const isOpen = openProp ?? uncontrolledOpen;
  // Read at event time, so a functional update sees the latest state in
  // controlled and uncontrolled mode alike.
  const isOpenRef = useRef(isOpen);
  useLayoutEffect(() => {
    isOpenRef.current = isOpen;
  }, [isOpen]);
  const setIsOpen = useCallback(
    (next: boolean | ((prev: boolean) => boolean)) => {
      const resolved = typeof next === "function" ? next(isOpenRef.current) : next;
      if (resolved === isOpenRef.current) return;
      if (openProp === undefined) setUncontrolledOpen(resolved);
      onOpenChange?.(resolved);
    },
    [openProp, onOpenChange]
  );

  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isKeyboardNav, setIsKeyboardNav] = useState(false);

  // The element the list positions against and measures: the anchor when
  // there is one, otherwise the trigger.
  const anchorRef = useRef<HTMLElement | null>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const referenceRef = useRef<HTMLElement | null>(null);
  // A wrapping <label> is part of the reference's hit area: the browser
  // forwards its clicks to the input, so it must not count as outside.
  const labelRef = useRef<HTMLElement | null>(null);
  const floatingRef = useRef<HTMLDivElement | null>(null);

  // Reset highlight and keyboard nav when closing
  useEffect(() => {
    if (!isOpen) {
      setHighlightedIndex(-1);
      setIsKeyboardNav(false);
    }
  }, [isOpen]);

  const { refs, floatingStyles, isPositioned } = useFloating({
    open: isOpen,
    placement: "bottom-start",
    middleware: [
      // 6px wider on each side than the reference, shifted start-ward by
      // 6px: with the list's 4px inset and its 1px border, the rows'
      // bounding boxes then align flush with the reference's content, inside
      // its own border. crossAxis is direction-aware, so RTL mirrors.
      offset({ mainAxis: 4, crossAxis: -6 }),
      flip(),
      shift({ padding: 8 }),
      size({
        apply({ rects, elements }) {
          Object.assign(elements.floating.style, {
            width: `${rects.reference.width + 12}px`,
          });
        },
      }),
    ],
    whileElementsMounted: autoUpdate,
  });

  const setReference = useCallback(
    (node: HTMLElement | null) => {
      referenceRef.current = node;
      labelRef.current = node?.closest("label") ?? null;
      refs.setReference(node);
    },
    [refs]
  );
  const setAnchorRef = useCallback(
    (node: HTMLElement | null) => {
      anchorRef.current = node;
      setReference(node ?? triggerRef.current);
    },
    [setReference]
  );
  const setTriggerRef = useCallback(
    (node: HTMLElement | null) => {
      triggerRef.current = node;
      if (anchorRef.current === null) setReference(node);
    },
    [setReference]
  );
  const setFloatingRef = useCallback(
    (node: HTMLDivElement | null) => {
      floatingRef.current = node;
      refs.setFloating(node);
    },
    [refs]
  );
  const focusTrigger = useCallback(() => {
    triggerRef.current?.focus();
  }, []);

  // Otherwise a label click dismisses the list and the forwarded click
  // reopens it, so a second click on the label never closes it.
  useClickOutside<HTMLElement>(
    [referenceRef, labelRef, floatingRef],
    useCallback(() => {
      setIsOpen(false);
      setIsKeyboardNav(false);
    }, [setIsOpen]),
    isOpen
  );

  return {
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    isKeyboardNav,
    setIsKeyboardNav,
    setAnchorRef,
    setTriggerRef,
    focusTrigger,
    floatingRef,
    setFloatingRef,
    floatingStyles,
    isPositioned,
  };
}
