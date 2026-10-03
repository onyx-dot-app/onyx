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
  type ReferenceType,
} from "@floating-ui/react-dom";
import { useClickOutside } from "@opal/hooks/useClickOutside";
import type {
  DropdownRow,
  NavItem,
  RowGroup,
} from "@opal/components/dropdown/types";

// =============================================================================
// HOOK: useFoldedGroups
// =============================================================================

interface UseFoldedGroupsProps {
  isOpen: boolean;
  /** Post-filter groups in render order. */
  groups: RowGroup[];
  isSelected: (row: DropdownRow) => boolean;
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
    (group: RowGroup) => {
      if (!group.foldable || group.title === undefined) return true;
      const choice = toggled.get(group.title);
      if (choice !== undefined) return choice;
      return searching || group.rows.some(sessionIsSelected);
    },
    [toggled, searching, sessionIsSelected]
  );

  const toggleGroup = useCallback(
    (group: RowGroup) => {
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
 * order and what Enter and ArrowRight do to each. Read through a ref at
 * event time, so the handler never goes stale and the list never
 * re-renders the trigger.
 */
export interface ListModel {
  items: NavItem[];
  /** Enter, or a click: pick, run, flip, unfold or create. */
  activate: (item: NavItem) => void;
  /** ArrowRight: the row's secondary control. Returns whether it took the key. */
  secondary: (item: NavItem) => boolean;
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
 * and wrap around from the last row to the first, Enter activates the
 * highlighted stop, ArrowRight reaches a row's secondary control, and
 * Escape closes. A closed list leaves Tab alone, so it moves on as normal.
 * Physical focus stays on the trigger or the search field; the highlight
 * moves and `aria-activedescendant` follows it. A handler that ran before
 * this one and cancelled the event keeps the key.
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
      return item !== undefined && !(item.kind === "row" && item.row.disabled);
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
        case "ArrowRight": {
          // Only a row with a secondary control takes the key; a type-in
          // keeps it for its caret otherwise.
          if (!isOpen) break;
          const item = listRef.current.items[highlightedIndex];
          if (item && listRef.current.secondary(item)) e.preventDefault();
          break;
        }
        case "Tab":
          if (!isOpen) break;
          // Inside the list Tab walks the stops, both ways, wrapping.
          e.preventDefault();
          setIsKeyboardNav(true);
          setHighlightedIndex(e.shiftKey ? previous : next);
          break;
        case "Enter": {
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
          const item = listRef.current.items[highlightedIndex];
          if (item) listRef.current.activate(item);
          break;
        }
        case "Escape":
          e.preventDefault();
          setIsOpen(false);
          setIsKeyboardNav(false);
          break;
      }
    },
    [
      isOpen,
      highlightedIndex,
      listRef,
      next,
      previous,
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

/**
 * `"anchor"` matches the anchor's width (6px wider on each side, so the
 * rows line up under its content); a preset is a fixed width.
 */
export type DropdownWidth = "anchor" | "sm" | "md" | "lg" | "xl";

/** A rectangle to position against, like a text caret: no element needed. */
export interface DropdownVirtualAnchor {
  getBoundingClientRect: () => DOMRect;
  /** An element in the same scroll context, so the list follows it. */
  contextElement?: Element;
}

interface UseDropdownOverlayProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  width: DropdownWidth;
  virtualAnchor?: DropdownVirtualAnchor;
}

/**
 * Everything the overlay shares across triggers: open, highlight and
 * keyboard-nav state with their close-reset, the floating-ui positioning
 * (anchor width or a preset, flip and shift), the refs, and outside-click
 * dismissal scoped to the reference element, its label and the portal.
 */
export function useDropdownOverlay({
  open: openProp,
  onOpenChange,
  width,
  virtualAnchor,
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
      const resolved =
        typeof next === "function" ? next(isOpenRef.current) : next;
      if (resolved === isOpenRef.current) return;
      if (openProp === undefined) setUncontrolledOpen(resolved);
      onOpenChange?.(resolved);
    },
    [openProp, onOpenChange]
  );

  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isKeyboardNav, setIsKeyboardNav] = useState(false);

  // The element the list positions against and measures: the anchor when
  // there is one, otherwise the trigger that opened it.
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

  const matchAnchor = width === "anchor";
  const { refs, floatingStyles, isPositioned } = useFloating<ReferenceType>({
    open: isOpen,
    placement: "bottom-start",
    middleware: [
      // Matching the anchor: 6px wider on each side than it, shifted
      // start-ward by 6px: with the list's 4px inset and its 1px border, the
      // rows' bounding boxes then align flush with the anchor's content,
      // inside its own border. crossAxis is direction-aware, so RTL mirrors.
      offset({ mainAxis: 4, crossAxis: matchAnchor ? -6 : 0 }),
      flip(),
      shift({ padding: 8 }),
      ...(matchAnchor
        ? [
            size({
              apply({ rects, elements }) {
                Object.assign(elements.floating.style, {
                  width: `${rects.reference.width + 12}px`,
                });
              },
            }),
          ]
        : []),
    ],
    whileElementsMounted: autoUpdate,
  });

  const setReference = useCallback(
    (node: HTMLElement | null) => {
      referenceRef.current = node;
      labelRef.current = node?.closest("label") ?? null;
      if (!virtualAnchor) refs.setReference(node);
    },
    [refs, virtualAnchor]
  );
  useEffect(() => {
    if (virtualAnchor) refs.setReference(virtualAnchor);
  }, [refs, virtualAnchor]);

  const setAnchorRef = useCallback(
    (node: HTMLElement | null) => {
      anchorRef.current = node;
      setReference(node ?? triggerRef.current);
    },
    [setReference]
  );
  // The trigger that opened the list, or the last one mounted: it takes
  // focus back after a pick and anchors the list when nothing else does.
  const setTriggerRef = useCallback(
    (node: HTMLElement | null) => {
      triggerRef.current = node;
      if (anchorRef.current === null) setReference(node);
    },
    [setReference]
  );
  const releaseTriggerRef = useCallback(
    (node: HTMLElement | null) => {
      if (triggerRef.current === node) setTriggerRef(null);
    },
    [setTriggerRef]
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
    releaseTriggerRef,
    focusTrigger,
    floatingRef,
    setFloatingRef,
    floatingStyles,
    isPositioned,
  };
}
