"use client";

import "@opal/components/dropdown/styles.css";
import React, {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Slot } from "@radix-ui/react-slot";
import { useOpalStrings } from "@opal/strings";
import {
  DropdownContext,
  useDropdownContext,
  type DropdownContextValue,
  type DropdownTriggerProps,
} from "@opal/components/dropdown/context";
import {
  useDropdownKeyboard,
  useDropdownOverlay,
  useFoldedGroups,
  type DropdownTabKey,
  type DropdownVirtualAnchor,
  type ListModel,
} from "@opal/components/dropdown/hooks";
import {
  buildNavItems,
  filterGroups,
  flattenGroups,
  isOption,
  navItemElementId,
  normalizeItems,
  optionMatchesExactly,
  rowElementId,
  rowKey,
} from "@opal/components/dropdown/model";
import { DropdownList } from "@opal/components/dropdown/list";
import type {
  DropdownItem,
  DropdownMenuItem,
  DropdownMode,
  DropdownOption,
  DropdownRow,
  NavItem,
  RowGroup,
} from "@opal/components/dropdown/types";

// ---------------------------------------------------------------------------
// Dropdown
// ---------------------------------------------------------------------------

interface DropdownProps {
  /** Controlled open state. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** A disabled dropdown never opens and renders no list. */
  disabled?: boolean;
  /**
   * Prefix for the list's and the rows' element ids, so a form field can
   * tie its label and messages to them. Generated when left out.
   */
  id?: string;
  /**
   * A rectangle to position against instead of an element, like a text
   * caret. Takes precedence over `Dropdown.Anchor` and the trigger.
   */
  virtualAnchor?: DropdownVirtualAnchor;
  /** Where the list portals to, for a dropdown inside a modal. */
  container?: HTMLElement | null;
  /**
   * What Tab does while the list is open. By default a type-in trigger
   * walks the rows and any other trigger closes the list and lets focus
   * move on; set it to make every trigger behave one way.
   */
  tabKey?: DropdownTabKey;
  children: React.ReactNode;
}

const EMPTY_LIST: ListModel = {
  items: [],
  activate: () => {},
  secondary: () => false,
};

/**
 * A floating list under a trigger, with the keyboard, search, groups and
 * folding handled once for every trigger. Compose it from `Dropdown.Trigger`
 * (what opens it and takes the keyboard), an optional `Dropdown.Anchor`
 * (what it positions against, when that is not the trigger) and
 * `Dropdown.Data` (the rows, as data).
 */
function Dropdown({
  open,
  onOpenChange,
  disabled = false,
  id: idProp,
  virtualAnchor,
  container,
  tabKey,
  children,
}: DropdownProps) {
  const autoId = useId();
  const id = idProp ?? `dropdown-${autoId}`;
  const overlay = useDropdownOverlay({
    open,
    onOpenChange,
    disabled,
    virtualAnchor,
  });
  const {
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    setIsKeyboardNav,
  } = overlay;

  const listRef = useRef<ListModel>(EMPTY_LIST);
  const [mode, setMode] = useState<DropdownMode>("picker");
  const [activeId, setActiveId] = useState<string | undefined>(undefined);

  const { handleKeyDown } = useDropdownKeyboard({
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    setIsKeyboardNav,
    listRef,
    tabKey,
  });

  const getTriggerProps = useCallback(
    ({ typeIn }: { typeIn: boolean }): DropdownTriggerProps => ({
      role: mode === "picker" ? "combobox" : undefined,
      "aria-expanded": isOpen,
      "aria-haspopup": mode === "picker" ? "listbox" : "menu",
      "aria-controls": `${id}-listbox`,
      "aria-activedescendant": isOpen ? activeId : undefined,
      "aria-autocomplete": typeIn ? "list" : undefined,
      // A type-in's letters are its filter; any other trigger types ahead.
      onKeyDown: (event) =>
        handleKeyDown(event, { typeIn, typeAhead: !typeIn, textField: typeIn }),
    }),
    [mode, isOpen, activeId, id, handleKeyDown]
  );

  const value = useMemo<DropdownContextValue>(
    () => ({
      id,
      disabled,
      container,
      isOpen,
      setIsOpen,
      highlightedIndex,
      setHighlightedIndex,
      isKeyboardNav: overlay.isKeyboardNav,
      setIsKeyboardNav,
      setAnchorRef: overlay.setAnchorRef,
      setTriggerRef: overlay.setTriggerRef,
      releaseTriggerRef: overlay.releaseTriggerRef,
      focusTrigger: overlay.focusTrigger,
      floatingRef: overlay.floatingRef,
      setFloatingRef: overlay.setFloatingRef,
      floatingStyles: overlay.floatingStyles,
      isPositioned: overlay.isPositioned,
      listRef,
      mode,
      setMode,
      activeId,
      setActiveId,
      handleKeyDown,
      getTriggerProps,
    }),
    [
      id,
      disabled,
      container,
      isOpen,
      setIsOpen,
      highlightedIndex,
      setHighlightedIndex,
      overlay.isKeyboardNav,
      setIsKeyboardNav,
      overlay.setAnchorRef,
      overlay.setTriggerRef,
      overlay.releaseTriggerRef,
      overlay.focusTrigger,
      overlay.floatingRef,
      overlay.setFloatingRef,
      overlay.floatingStyles,
      overlay.isPositioned,
      mode,
      activeId,
      handleKeyDown,
      getTriggerProps,
    ]
  );

  return (
    <DropdownContext.Provider value={value}>
      {children}
    </DropdownContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Dropdown.Anchor
// ---------------------------------------------------------------------------

interface DropdownAnchorProps {
  /** Merge onto the child element instead of rendering a wrapper. */
  asChild?: boolean;
  children: React.ReactNode;
}

/**
 * The element the list positions against and matches in width, when that
 * is not the trigger: a whole field whose trigger is one control inside it,
 * or a row opened from a button at its end. Left out, the trigger anchors.
 */
function DropdownAnchor({ asChild, children }: DropdownAnchorProps) {
  const { setAnchorRef } = useDropdownContext();
  const Component = asChild ? Slot : "div";
  return <Component ref={setAnchorRef}>{children}</Component>;
}

// ---------------------------------------------------------------------------
// Dropdown.Trigger
// ---------------------------------------------------------------------------

/**
 * What a click does: `"toggle"` opens and closes, like a button; `"open"`
 * only opens, like a type-in whose second click must not close the list;
 * `"none"` leaves clicks to the child.
 */
type DropdownTriggerBehavior = "toggle" | "open" | "none";

interface DropdownTriggerElementProps {
  /** Merge onto the child element instead of rendering a `<button>`. */
  asChild?: boolean;
  /**
   * The trigger is a text input whose text filters the list (pass the text
   * to `Dropdown.Data` as `query`). Announces list autocomplete and opens
   * on click instead of toggling.
   */
  typeIn?: boolean;
  /** @default `"open"` for a type-in, `"toggle"` otherwise */
  behavior?: DropdownTriggerBehavior;
  children: React.ReactNode;
}

/**
 * The element that holds focus and takes the keyboard: arrows walk the
 * list, Enter activates, Escape closes. It also carries the ids that tie
 * it to the list, and for a picker the combobox role. A dropdown may have
 * several triggers; the one that opened the list anchors it and takes
 * focus back.
 */
function DropdownTrigger({
  asChild,
  typeIn = false,
  behavior = typeIn ? "open" : "toggle",
  children,
}: DropdownTriggerElementProps) {
  const {
    disabled,
    setIsOpen,
    setHighlightedIndex,
    setTriggerRef,
    releaseTriggerRef,
    getTriggerProps,
  } = useDropdownContext();
  const nodeRef = useRef<HTMLElement | null>(null);
  const ref = useCallback(
    (node: HTMLElement | null) => {
      if (node) {
        nodeRef.current = node;
        setTriggerRef(node);
      } else {
        releaseTriggerRef(nodeRef.current);
        nodeRef.current = null;
      }
    },
    [setTriggerRef, releaseTriggerRef]
  );
  // This trigger is the one in use: it anchors the list and takes focus back.
  const claim = () => setTriggerRef(nodeRef.current);

  const triggerProps = getTriggerProps({ typeIn });
  const onKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (disabled) return;
    claim();
    triggerProps.onKeyDown(event);
  };
  const onClick = (event: React.MouseEvent) => {
    if (behavior === "none" || disabled || event.defaultPrevented) return;
    claim();
    if (behavior === "open") {
      setIsOpen(true);
      return;
    }
    setIsOpen((prev) => {
      if (!prev) setHighlightedIndex(-1);
      return !prev;
    });
  };

  const Component = asChild ? Slot : "button";
  return (
    <Component
      ref={ref}
      {...(asChild ? {} : { type: "button" as const })}
      {...triggerProps}
      onKeyDown={onKeyDown}
      onClick={onClick}
    >
      {children}
    </Component>
  );
}

// ---------------------------------------------------------------------------
// Dropdown.Data
// ---------------------------------------------------------------------------

interface DropdownDataBaseProps {
  /** Names the list for assistive technology. */
  label?: string;
  /**
   * A type-in trigger's text. Filters the rows by title, value and
   * keywords. A group whose title matches keeps all its rows.
   */
  query?: string;
  /**
   * A search field pinned above the rows, for a trigger with nothing to
   * type. It takes focus when the list opens; Escape hands focus back to
   * the trigger. `onChange` reports the text, and `""` when the list closes.
   */
  search?: { placeholder: string; onChange?: (query: string) => void };
  /**
   * Text whose exact match (an option's value or title) also reads as
   * selected, for a type-in whose text is the pick before it is committed.
   * The first match only.
   */
  exactText?: string;
  /**
   * Move the highlight to the option the query matches exactly, unless the
   * keyboard is driving. A type-in combobox behaviour.
   */
  highlightExactQuery?: boolean;
  /**
   * A create row pinned first, showing `text`; a click or Enter commits it.
   * Shown only while given.
   */
  create?: { text: string; onCreate: (text: string) => void };
  /**
   * Rows the query filtered out stay, under a group with this title, so a
   * search narrows the list without hiding the rest.
   */
  otherOptionsTitle?: string;
  /** Max height of the list in CSS units. Defaults to 15rem. */
  maxHeight?: string;
  /**
   * The rows scrolled near their end. `shown` is the options on show, a
   * folded group's rows left out, so a caller pages in only what is being
   * read.
   */
  onReachEnd?: (shown: DropdownOption[]) => void;
}

type DropdownPickerProps = DropdownDataBaseProps & {
  /** The rows: options, other rows and groups, in order. */
  items: DropdownItem[];
  /** A click or Enter on an option. What a pick means is the caller's. */
  onSelect: (option: DropdownOption) => void;
  /**
   * Close after a pick.
   * @default true for a single `value`, false for `values`
   */
  closeOnSelect?: boolean;
};

/**
 * A picker: something is selected. With `value` one row reads as
 * selected; with `values` every one does, and the list stays open for
 * more picks.
 */
type DropdownSinglePickerProps = DropdownPickerProps & {
  value: string;
  values?: never;
};
type DropdownMultiPickerProps = DropdownPickerProps & {
  values: ReadonlySet<string>;
  value?: never;
};

/** A menu: commands, toggles and custom rows. Nothing is selected, so no options. */
type DropdownMenuProps = DropdownDataBaseProps & {
  items: DropdownMenuItem[];
  value?: never;
  values?: never;
  onSelect?: never;
  closeOnSelect?: never;
};

type DropdownDataProps =
  | DropdownSinglePickerProps
  | DropdownMultiPickerProps
  | DropdownMenuProps;

/**
 * The rows, as data, and the list that renders them in a portal. Filters by
 * the trigger's text or its own search field, folds groups, keeps the
 * keyboard order in step with what is on show, and marks the selection.
 * With a `value` or `values` it is a picker (a listbox); without, a menu.
 */
function DropdownData(props: DropdownDataProps) {
  const {
    items,
    label,
    query,
    search,
    exactText,
    highlightExactQuery = false,
    create,
    otherOptionsTitle,
    maxHeight,
    onReachEnd,
    value,
    values,
    onSelect,
  } = props;
  const isPicker = value !== undefined || values !== undefined;
  const closeOnSelect = props.closeOnSelect ?? values === undefined;
  const {
    id,
    disabled,
    container,
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    isKeyboardNav,
    setIsKeyboardNav,
    focusTrigger,
    floatingRef,
    setFloatingRef,
    floatingStyles,
    isPositioned,
    listRef,
    mode,
    setMode,
    setActiveId,
    handleKeyDown,
  } = useDropdownContext();
  const strings = useOpalStrings();

  // The trigger reads the mode for its role, before the first paint.
  useLayoutEffect(() => {
    setMode(isPicker ? "picker" : "menu");
  }, [isPicker, setMode]);

  // The search field's text is transient: it clears with the list.
  const [searchText, setSearchText] = useState("");
  const searchOnChange = search?.onChange;
  useEffect(() => {
    if (isOpen) return;
    setSearchText("");
    searchOnChange?.("");
  }, [isOpen, searchOnChange]);
  const filterText = query ?? (search ? searchText : "");
  const searching = filterText.trim() !== "";

  const groups = useMemo(() => normalizeItems(items), [items]);
  const allRows = useMemo(() => flattenGroups(groups), [groups]);
  const allOptions = useMemo(() => allRows.filter(isOption), [allRows]);

  const visibleGroups = useMemo(() => {
    const filtered = filterGroups(groups, filterText);
    if (searching && otherOptionsTitle !== undefined) {
      const visible = new Set(flattenGroups(filtered).map(rowKey));
      const unmatched = allRows.filter((row) => !visible.has(rowKey(row)));
      if (unmatched.length > 0) {
        return [
          ...filtered,
          { key: "other", title: otherOptionsTitle, rows: unmatched },
        ];
      }
    }
    return filtered;
  }, [groups, filterText, searching, otherOptionsTitle, allRows]);

  // The selection: a picked option, or a toggle that is on. Both keep a
  // foldable group open when the list opens.
  const isSelected = useCallback(
    (row: DropdownRow) => {
      if (row.kind === "option") {
        return values ? values.has(row.value) : row.value === value;
      }
      return row.kind === "toggle" && row.checked;
    },
    [values, value]
  );
  const { foldedGroups, toggleGroup } = useFoldedGroups({
    isOpen,
    groups: visibleGroups,
    isSelected,
    searching,
  });
  const shownOptions = useMemo(
    () =>
      foldedGroups
        .filter((group) => !group.folded)
        .flatMap((group) => group.rows)
        .filter(isOption),
    [foldedGroups]
  );

  const navItems = useMemo(
    () => buildNavItems(foldedGroups, create?.text),
    [foldedGroups, create?.text]
  );

  // What Enter, or a click, does to a stop. An action or a custom row
  // closes the list unless it asked to stay; a toggle and a multi pick keep
  // it open for the next one.
  const onCreate = create?.onCreate;
  const activateRow = useCallback(
    (row: DropdownRow) => {
      if (row.disabled) return;
      switch (row.kind) {
        case "option":
          onSelect?.(row);
          if (closeOnSelect) setIsOpen(false);
          break;
        case "action":
          // A link action's row is an anchor: the click itself navigates.
          row.onSelect?.();
          if (!row.keepOpen) setIsOpen(false);
          break;
        case "toggle":
          row.onCheckedChange(!row.checked);
          break;
        case "custom":
          row.onActivate?.();
          if (!row.keepOpen) setIsOpen(false);
          break;
      }
    },
    [onSelect, closeOnSelect, setIsOpen]
  );
  const activate = useCallback(
    (item: NavItem) => {
      if (item.kind === "row") {
        const { row } = item;
        if (row.kind === "action" && row.href !== undefined) {
          // Enter clicks the anchor, so the browser navigates as it would
          // for a pointer click; the click handler then runs activateRow.
          document.getElementById(rowElementId(id, row.id))?.click();
          return;
        }
        activateRow(row);
      } else if (item.kind === "create") onCreate?.(item.text);
      else toggleGroup(item.group);
    },
    [id, activateRow, onCreate, toggleGroup]
  );
  const secondary = useCallback((item: NavItem) => {
    if (item.kind !== "row" || item.row.kind !== "custom") return false;
    if (!item.row.onSecondary || item.row.disabled) return false;
    item.row.onSecondary();
    return true;
  }, []);

  // The keyboard reads the stops through the ref at event time; the
  // trigger reads the highlighted stop's id for aria-activedescendant.
  useLayoutEffect(() => {
    listRef.current = { items: navItems, activate, secondary };
  });
  useLayoutEffect(() => {
    setActiveId(
      highlightedIndex >= 0
        ? navItemElementId(id, navItems[highlightedIndex])
        : undefined
    );
  }, [id, navItems, highlightedIndex, setActiveId]);

  // The stops changed under a highlight the caller did not move (a type-in
  // filtered the rows): follow the highlighted stop to its new index, or
  // clear the highlight when it filtered out. A highlight the caller moved
  // in the same render (typing resets it to the first row) is theirs.
  const lastNavRef = useRef<{ items: NavItem[]; index: number } | null>(null);
  useLayoutEffect(() => {
    const last = lastNavRef.current;
    lastNavRef.current = { items: navItems, index: highlightedIndex };
    if (!last || last.items === navItems) return;
    if (last.index !== highlightedIndex || highlightedIndex < 0) return;
    const wanted = navItemElementId(id, last.items[last.index]);
    const index = navItems.findIndex(
      (item) => navItemElementId(id, item) === wanted
    );
    if (index !== highlightedIndex) setHighlightedIndex(index);
  }, [id, navItems, highlightedIndex, setHighlightedIndex]);

  // A type-in combobox highlights the option its text matches exactly; the
  // keyboard, once it drives, keeps its own stop.
  useEffect(() => {
    if (!highlightExactQuery || isKeyboardNav || !isOpen || !searching) {
      return;
    }
    const index = navItems.findIndex(
      (item) =>
        item.kind === "row" &&
        item.row.kind === "option" &&
        optionMatchesExactly(item.row, filterText)
    );
    if (index >= 0) setHighlightedIndex(index);
  }, [
    highlightExactQuery,
    isKeyboardNav,
    isOpen,
    searching,
    navItems,
    filterText,
    setHighlightedIndex,
  ]);

  // The first exact match reads as selected, like the selection itself.
  const exactValue = useMemo(() => {
    if (exactText === undefined) return undefined;
    return allOptions.find((option) => optionMatchesExactly(option, exactText))
      ?.value;
  }, [allOptions, exactText]);

  const handleGroupToggle = useCallback(
    (group: RowGroup) => toggleGroup(group),
    [toggleGroup]
  );

  return (
    <DropdownList
      ref={floatingRef}
      listId={id}
      mode={mode}
      container={container}
      isOpen={isOpen}
      disabled={disabled}
      label={label ?? ""}
      floatingStyles={floatingStyles}
      isPositioned={isPositioned}
      setFloatingRef={setFloatingRef}
      groups={foldedGroups}
      emptySet={allRows.length === 0}
      isSelected={isSelected}
      exactValue={exactValue}
      highlightedIndex={highlightedIndex}
      keyboardNav={isKeyboardNav}
      onActivate={activateRow}
      onToggleGroup={handleGroupToggle}
      create={create}
      maxHeight={maxHeight}
      onReachEnd={onReachEnd && (() => onReachEnd(shownOptions))}
      // The pointer took over: the keyboard highlight yields to the row's
      // own hover on whatever the pointer is on.
      onMouseMove={() => {
        if (isKeyboardNav) {
          setIsKeyboardNav(false);
          setHighlightedIndex(-1);
        }
      }}
      searchField={
        search
          ? {
              value: searchText,
              placeholder:
                search.placeholder || strings.selectSearchPlaceholder,
              onChange: (next) => {
                setSearchText(next);
                search.onChange?.(next);
                // Typing never highlights; only walking the list does.
                setHighlightedIndex(-1);
                setIsKeyboardNav(false);
              },
              onKeyDown: (event) => {
                // The field's letters are the filter, so no type-ahead; Tab
                // follows the dropdown's setting, else leaves.
                handleKeyDown(event, {
                  typeIn: false,
                  typeAhead: false,
                  textField: true,
                });
                // Escape closes the list; focus goes back to the trigger so
                // the field is not left orphaned.
                if (event.key === "Escape") focusTrigger();
              },
            }
          : undefined
      }
    />
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

const DropdownCompound = Object.assign(Dropdown, {
  Anchor: DropdownAnchor,
  Trigger: DropdownTrigger,
  Data: DropdownData,
});

export {
  DropdownCompound as Dropdown,
  type DropdownProps,
  type DropdownAnchorProps,
  type DropdownTriggerElementProps as DropdownTriggerProps,
  type DropdownTriggerBehavior,
  type DropdownDataProps,
  type DropdownTabKey,
  type DropdownVirtualAnchor,
};
