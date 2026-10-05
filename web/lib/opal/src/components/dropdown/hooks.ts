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
import type {
  DropdownAlign,
  DropdownRow,
  DropdownSide,
  DropdownWidth,
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
  /** The view on show. A new view starts its groups afresh. */
  viewKey: string;
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
  viewKey,
}: UseFoldedGroupsProps) {
  // The selection as the session found it. Held as state, not derived, so
  // the live selection cannot re-fold groups afterwards.
  const [sessionIsSelected, setSessionIsSelected] = useState(() => isSelected);
  // Keyed by the view it was made for: a new view's first render sees an
  // empty map, before the effect below replaces it.
  const [toggledState, setToggledState] = useState<{
    viewKey: string;
    map: ReadonlyMap<string, boolean>;
  }>({ viewKey, map: new Map() });
  const toggled: ReadonlyMap<string, boolean> =
    toggledState.viewKey === viewKey ? toggledState.map : new Map();
  const setToggled = useCallback(
    (map: ReadonlyMap<string, boolean>) => setToggledState({ viewKey, map }),
    [viewKey]
  );

  const latestIsSelected = useRef(isSelected);
  useEffect(() => {
    latestIsSelected.current = isSelected;
  });
  useEffect(() => {
    if (!isOpen) return;
    setSessionIsSelected(() => latestIsSelected.current);
    setToggled(new Map());
  }, [isOpen, searching, viewKey]);

  const isGroupOpen = useCallback(
    (group: RowGroup) => {
      if (!group.foldable || group.title === undefined) return true;
      const choice = toggled.get(group.key);
      if (choice !== undefined) return choice;
      return searching || group.rows.some(sessionIsSelected);
    },
    [toggled, searching, sessionIsSelected]
  );

  const toggleGroup = useCallback(
    (group: RowGroup) => {
      if (group.title === undefined) return;
      const open = isGroupOpen(group);
      setToggled(new Map(toggled).set(group.key, !open));
    },
    [isGroupOpen, toggled, setToggled]
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
  /** Escape: back one view. Returns whether there was one to leave. */
  back: () => boolean;
}

/**
 * What Tab does while the list is open: `"walk"` moves the highlight
 * through the rows and wraps, for a field that must keep focus; `"leave"`
 * closes the list and lets focus move on, as a native menu does.
 */
export type DropdownTabKey = "walk" | "leave";

/** How the key arrived: from which kind of trigger, and whether letters type ahead. */
export interface DropdownKeyOptions {
  /** A text input: its letters are the filter, and Tab walks the rows. */
  typeIn: boolean;
  /** Letters jump the highlight to the row they start. */
  typeAhead: boolean;
  /**
   * A text field has focus (the type-in, or the search field): the left
   * and right arrows move its caret, so the list leaves them alone.
   */
  textField: boolean;
}

interface UseDropdownKeyboardProps {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  highlightedIndex: number;
  setHighlightedIndex: (index: number | ((prev: number) => number)) => void;
  setIsKeyboardNav: (isKeyboard: boolean) => void;
  listRef: React.RefObject<ListModel>;
  /** Overrides what Tab does, for every trigger of this dropdown. */
  tabKey?: DropdownTabKey;
}

/** The text a type-ahead matches: a row's title, or a custom row's first keyword. */
function rowLabel(row: DropdownRow): string {
  if (row.kind === "custom") return row.keywords?.[0] ?? "";
  return row.title;
}

const TYPE_AHEAD_RESET_MS = 500;

/**
 * Keyboard navigation for the list, the same for every trigger: Enter or
 * ArrowDown opens a closed list; open, the arrows and Tab walk the stops
 * and wrap around from the last row to the first, Enter activates the
 * highlighted stop, ArrowRight reaches a row's secondary control or
 * unfolds and enters a group, and Escape leaves a view or closes. A closed
 * list leaves Tab alone, so it moves on as normal.
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
  tabKey,
}: UseDropdownKeyboardProps) {
  // The letters typed in quick succession; they clear after a pause, so
  // "ba" finds Banana rather than cycling through the B's.
  const typeAheadRef = useRef("");
  const typeAheadTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(typeAheadTimer.current), []);
  // The letters go with the list: a reopen starts a fresh prefix.
  useEffect(() => {
    if (isOpen) return;
    window.clearTimeout(typeAheadTimer.current);
    typeAheadRef.current = "";
  }, [isOpen]);

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

  // The next row, after the highlight and wrapping, whose label starts with
  // the typed letters; -1 when none does.
  const typeAheadMatch = useCallback(
    (text: string) => {
      const { items } = listRef.current;
      const count = items.length;
      for (let step = 1; step <= count; step++) {
        const index = (highlightedIndex + step) % count;
        const item = items[index];
        if (!item || item.kind !== "row" || item.row.disabled) continue;
        if (rowLabel(item.row).toLowerCase().startsWith(text)) return index;
      }
      return -1;
    },
    [listRef, highlightedIndex]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLElement>, options: DropdownKeyOptions) => {
      if (e.defaultPrevented) return;
      const tab = tabKey ?? (options.typeIn ? "walk" : "leave");
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setIsKeyboardNav(true);
          if (!isOpen) {
            // Opening lands on the first enabled stop.
            setIsOpen(true);
            setHighlightedIndex(next(-1));
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
          if (!isOpen) break;
          const { items } = listRef.current;
          const item = items[highlightedIndex];
          if (!item) break;
          // On a group's title: unfold it, or step into its first row.
          if (item.kind === "group" && !options.textField) {
            e.preventDefault();
            if (item.group.folded) {
              listRef.current.activate(item);
            } else {
              // The first enabled row of this group, if it has one.
              for (
                let index = highlightedIndex + 1;
                index < items.length;
                index++
              ) {
                const stop = items[index];
                if (stop?.kind !== "row" || stop.group !== item.group) break;
                if (stop.row.disabled) continue;
                setIsKeyboardNav(true);
                setHighlightedIndex(index);
                break;
              }
            }
            break;
          }
          // Otherwise only a row with a secondary control takes the key; a
          // text field keeps it for its caret.
          if (options.textField) break;
          if (listRef.current.secondary(item)) e.preventDefault();
          break;
        }
        case "Tab":
          if (!isOpen) break;
          if (tab === "leave") {
            // The list closes and focus moves on: the key keeps its default.
            setIsOpen(false);
            setIsKeyboardNav(false);
            break;
          }
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
          // Inside a view, Escape leaves it; at the root it closes.
          if (isOpen && listRef.current.back()) break;
          setIsOpen(false);
          setIsKeyboardNav(false);
          break;
        default: {
          // Type-ahead: a letter jumps to the row it starts. Only on a
          // trigger with nothing to type into; a type-in's letters filter.
          if (!options.typeAhead || !isOpen) break;
          if (e.key.length !== 1 || e.ctrlKey || e.metaKey || e.altKey) break;
          window.clearTimeout(typeAheadTimer.current);
          typeAheadRef.current += e.key.toLowerCase();
          typeAheadTimer.current = window.setTimeout(() => {
            typeAheadRef.current = "";
          }, TYPE_AHEAD_RESET_MS);
          const index = typeAheadMatch(typeAheadRef.current);
          if (index < 0) break;
          e.preventDefault();
          setIsKeyboardNav(true);
          setHighlightedIndex(index);
          break;
        }
      }
    },
    [
      isOpen,
      highlightedIndex,
      listRef,
      tabKey,
      next,
      previous,
      typeAheadMatch,
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

/** A rectangle to position against, like a text caret: no element needed. */
export interface DropdownVirtualAnchor {
  getBoundingClientRect: () => DOMRect;
  /** An element in the same scroll context, so the list follows it. */
  contextElement?: Element;
}

/** How far the list reaches past the anchor on its aligned side, in px. */
const PUNCH_OUT_PX = 6;

interface UseDropdownOverlayProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** A disabled dropdown never opens, from a click or a key alike. */
  disabled: boolean;
  virtualAnchor?: DropdownVirtualAnchor;
  /** A fixed width; left out, the list matches its anchor. */
  width?: DropdownWidth;
  align: DropdownAlign;
  side: DropdownSide;
}

/**
 * Everything the overlay shares across triggers: open, highlight and
 * keyboard-nav state with their close-reset, the floating-ui positioning
 * (the anchor's width, flip and shift), the refs, and outside-click
 * dismissal scoped to the reference element, its label and the portal.
 */
export function useDropdownOverlay({
  open: openProp,
  onOpenChange,
  disabled,
  virtualAnchor,
  width,
  align,
  side,
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
      if (resolved && disabled) return;
      if (openProp === undefined) setUncontrolledOpen(resolved);
      onOpenChange?.(resolved);
    },
    [openProp, onOpenChange, disabled]
  );

  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isKeyboardNav, setIsKeyboardNav] = useState(false);

  // The element the list positions against and measures: the anchor when
  // there is one, otherwise the trigger that opened it.
  const anchorRef = useRef<HTMLElement | null>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  // Every mounted trigger: a click on any of them is inside, so it toggles
  // rather than dismissing the list and then reopening it.
  const triggersRef = useRef(new Set<HTMLElement>());
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

  const widthRef = useRef(width);
  const { refs, floatingStyles, isPositioned, placement, update } =
    useFloating<ReferenceType>({
      open: isOpen,
      placement: `${side}-${align}`,
      middleware: [
        // Below the anchor, the list reaches 6px past it on its aligned side:
        // with its 4px inset and 1px border, the rows' bounding boxes then
        // align flush with the anchor's content, inside its own border.
        // Matched to the anchor it reaches 6px past both sides; a fixed width
        // includes that reach. A flyout beside the anchor lines its edge up
        // exactly. crossAxis is direction-aware, so RTL mirrors.
        offset({
          mainAxis: 4,
          crossAxis:
            side === "right"
              ? 0
              : align === "end"
                ? PUNCH_OUT_PX
                : -PUNCH_OUT_PX,
        }),
        flip(),
        shift({ padding: 8 }),
        size({
          apply({ rects, elements }) {
            // Read through a ref: floating-ui compares middleware by source
            // text, so a closure over `width` would never be seen to change.
            // Inline, so a fixed width also beats the stylesheet's floor.
            const fixed = widthRef.current;
            Object.assign(
              elements.floating.style,
              fixed !== undefined
                ? { width: `${fixed}rem`, minWidth: `${fixed}rem` }
                : {
                    width: `${rects.reference.width + 2 * PUNCH_OUT_PX}px`,
                    // Back from a fixed width: the stylesheet's floor again.
                    minWidth: "",
                  }
            );
          },
        }),
      ],
      whileElementsMounted: autoUpdate,
    });
  // A view can change the width while the list is open: measure again.
  useLayoutEffect(() => {
    widthRef.current = width;
    update();
  }, [width, update]);

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
  // focus back after a pick and anchors the list when nothing else does. A
  // trigger that is the control inside an Opal field (a type-in's <input>)
  // anchors to the field's chrome, so the list lines up with the field, not
  // with the control 7px inside it.
  const setTriggerRef = useCallback(
    (node: HTMLElement | null) => {
      triggerRef.current = node;
      if (anchorRef.current === null) {
        setReference(node?.closest<HTMLElement>(".opal-input") ?? node);
      }
    },
    [setReference]
  );
  // The active trigger unmounting hands over to another that is still
  // mounted, so a pick can still return focus and the list keeps an anchor.
  const releaseTriggerRef = useCallback(
    (node: HTMLElement | null) => {
      if (triggerRef.current !== node) return;
      const next =
        [...triggersRef.current].find((trigger) => trigger !== node) ?? null;
      setTriggerRef(next);
    },
    [setTriggerRef]
  );
  const registerTrigger = useCallback((node: HTMLElement) => {
    triggersRef.current.add(node);
  }, []);
  const unregisterTrigger = useCallback((node: HTMLElement) => {
    triggersRef.current.delete(node);
  }, []);
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

  // A mousedown anywhere else dismisses the list. Inside: the reference,
  // its wrapping label (otherwise a label click dismisses the list and the
  // forwarded click reopens it), the list, and every trigger.
  useEffect(() => {
    if (!isOpen) return;
    const onMouseDown = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      const inside = [
        referenceRef.current,
        labelRef.current,
        floatingRef.current,
        ...triggersRef.current,
      ].some((el) => el?.contains(target));
      if (inside) return;
      setIsOpen(false);
      setIsKeyboardNav(false);
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [isOpen, setIsOpen]);

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
    registerTrigger,
    unregisterTrigger,
    focusTrigger,
    floatingRef,
    setFloatingRef,
    floatingStyles,
    isPositioned,
    // The edge the list grows from: its top, unless it was flipped above
    // the anchor or flies out beside it bottoms-aligned.
    anchoredEdge:
      placement.startsWith("top") ||
      (!placement.startsWith("bottom") && placement.endsWith("-end"))
        ? ("bottom" as const)
        : ("top" as const),
  };
}
