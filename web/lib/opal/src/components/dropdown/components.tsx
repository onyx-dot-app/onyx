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
  type ListModel,
} from "@opal/components/dropdown/hooks";
import {
  buildNavItems,
  filterGroups,
  flattenGroups,
  navItemElementId,
  normalizeItems,
  optionMatchesExactly,
} from "@opal/components/dropdown/model";
import { DropdownList } from "@opal/components/dropdown/list";
import type {
  DropdownItem,
  DropdownOption,
  OptionGroup,
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
  children: React.ReactNode;
}

const EMPTY_LIST: ListModel = {
  items: [],
  onSelect: () => {},
  onToggleGroup: () => {},
  onCreate: () => {},
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
  children,
}: DropdownProps) {
  const autoId = useId();
  const id = idProp ?? `dropdown-${autoId}`;
  const overlay = useDropdownOverlay({ open, onOpenChange });
  const {
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    setIsKeyboardNav,
  } = overlay;

  const listRef = useRef<ListModel>(EMPTY_LIST);
  const [activeId, setActiveId] = useState<string | undefined>(undefined);

  const { handleKeyDown } = useDropdownKeyboard({
    isOpen,
    setIsOpen,
    highlightedIndex,
    setHighlightedIndex,
    setIsKeyboardNav,
    listRef,
  });

  const getTriggerProps = useCallback(
    ({ typeIn }: { typeIn: boolean }): DropdownTriggerProps => ({
      role: "combobox",
      "aria-expanded": isOpen,
      "aria-haspopup": "listbox",
      "aria-controls": `${id}-listbox`,
      "aria-activedescendant": isOpen ? activeId : undefined,
      "aria-autocomplete": typeIn ? "list" : undefined,
      onKeyDown: handleKeyDown,
    }),
    [isOpen, activeId, id, handleKeyDown]
  );

  const value = useMemo<DropdownContextValue>(
    () => ({
      id,
      disabled,
      isOpen,
      setIsOpen,
      highlightedIndex,
      setHighlightedIndex,
      isKeyboardNav: overlay.isKeyboardNav,
      setIsKeyboardNav,
      setAnchorRef: overlay.setAnchorRef,
      setTriggerRef: overlay.setTriggerRef,
      focusTrigger: overlay.focusTrigger,
      floatingRef: overlay.floatingRef,
      setFloatingRef: overlay.setFloatingRef,
      floatingStyles: overlay.floatingStyles,
      isPositioned: overlay.isPositioned,
      listRef,
      activeId,
      setActiveId,
      handleKeyDown,
      getTriggerProps,
    }),
    [
      id,
      disabled,
      isOpen,
      setIsOpen,
      highlightedIndex,
      setHighlightedIndex,
      overlay.isKeyboardNav,
      setIsKeyboardNav,
      overlay.setAnchorRef,
      overlay.setTriggerRef,
      overlay.focusTrigger,
      overlay.floatingRef,
      overlay.setFloatingRef,
      overlay.floatingStyles,
      overlay.isPositioned,
      activeId,
      handleKeyDown,
      getTriggerProps,
    ]
  );

  return (
    <DropdownContext.Provider value={value}>{children}</DropdownContext.Provider>
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

interface DropdownTriggerElementProps {
  /** Merge onto the child element instead of rendering a `<button>`. */
  asChild?: boolean;
  /**
   * The trigger is a text input whose text filters the list (pass the text
   * to `Dropdown.Data` as `query`). Announces list autocomplete.
   */
  typeIn?: boolean;
  children: React.ReactNode;
}

/**
 * The element that holds focus and takes the keyboard: arrows walk the
 * list, Enter picks, Escape closes. It also carries the combobox role and
 * the ids that tie it to the list. Opening and closing on click is the
 * child's own behaviour, since a button toggles while a type-in only opens.
 */
function DropdownTrigger({
  asChild,
  typeIn = false,
  children,
}: DropdownTriggerElementProps) {
  const { setTriggerRef, getTriggerProps } = useDropdownContext();
  const triggerProps = getTriggerProps({ typeIn });
  const Component = asChild ? Slot : "button";
  return (
    <Component
      ref={setTriggerRef}
      {...(asChild ? {} : { type: "button" as const })}
      {...triggerProps}
    >
      {children}
    </Component>
  );
}

// ---------------------------------------------------------------------------
// Dropdown.Data
// ---------------------------------------------------------------------------

interface DropdownDataProps {
  /** The rows: loose options and groups, in order. */
  items: DropdownItem[];
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
  /** The selected value: its row reads as selected. */
  value?: string;
  /** The selected values (a multi pick): every one reads as selected. */
  values?: ReadonlySet<string>;
  /**
   * Text whose exact match (a row's value or title) also reads as selected,
   * for a type-in whose text is the pick before it is committed. The first
   * match only.
   */
  exactText?: string;
  /**
   * Move the highlight to the row the query matches exactly, unless the
   * keyboard is driving. A type-in combobox behaviour.
   */
  highlightExactQuery?: boolean;
  /** A click or Enter on a row. Picking semantics are the caller's. */
  onSelect: (option: DropdownOption) => void;
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
   * The rows scrolled near their end. `shown` is the rows on show, a folded
   * group's rows left out, so a caller pages in only what is being read.
   */
  onReachEnd?: (shown: DropdownOption[]) => void;
}

/**
 * The rows, as data, and the list that renders them in a portal. Filters by
 * the trigger's text or its own search field, folds groups, keeps the
 * keyboard order in step with what is on show, and marks the selection.
 */
function DropdownData({
  items,
  label,
  query,
  search,
  value,
  values,
  exactText,
  highlightExactQuery = false,
  onSelect,
  create,
  otherOptionsTitle,
  maxHeight,
  onReachEnd,
}: DropdownDataProps) {
  const {
    id,
    disabled,
    isOpen,
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
    setActiveId,
    handleKeyDown,
  } = useDropdownContext();
  const strings = useOpalStrings();

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
  const allOptions = useMemo(() => flattenGroups(groups), [groups]);

  const visibleGroups = useMemo(() => {
    const filtered = filterGroups(groups, filterText);
    if (searching && otherOptionsTitle !== undefined) {
      const visible = new Set(
        flattenGroups(filtered).map((option) => option.value)
      );
      const unmatched = allOptions.filter(
        (option) => !visible.has(option.value)
      );
      if (unmatched.length > 0) {
        return [...filtered, { title: otherOptionsTitle, options: unmatched }];
      }
    }
    return filtered;
  }, [groups, filterText, searching, otherOptionsTitle, allOptions]);

  const isSelected = useCallback(
    (option: DropdownOption) =>
      values ? values.has(option.value) : option.value === value,
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
        .flatMap((group) => group.options),
    [foldedGroups]
  );

  const navItems = useMemo(
    () => buildNavItems(foldedGroups, create?.text),
    [foldedGroups, create?.text]
  );

  // The keyboard reads the stops through the ref at event time; the
  // trigger reads the highlighted stop's id for aria-activedescendant.
  const onCreate = create?.onCreate;
  useLayoutEffect(() => {
    listRef.current = {
      items: navItems,
      onSelect,
      onToggleGroup: toggleGroup,
      onCreate: onCreate ?? (() => {}),
    };
  });
  useLayoutEffect(() => {
    setActiveId(
      highlightedIndex >= 0
        ? navItemElementId(id, navItems[highlightedIndex])
        : undefined
    );
  }, [id, navItems, highlightedIndex, setActiveId]);

  // A type-in combobox highlights the row its text matches exactly; the
  // keyboard, once it drives, keeps its own stop.
  useEffect(() => {
    if (!highlightExactQuery || isKeyboardNav || !isOpen || !searching) {
      return;
    }
    const index = navItems.findIndex(
      (item) =>
        item.kind === "option" && optionMatchesExactly(item.option, filterText)
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
    (group: OptionGroup) => toggleGroup(group),
    [toggleGroup]
  );

  return (
    <DropdownList
      ref={floatingRef}
      listId={id}
      isOpen={isOpen}
      disabled={disabled}
      label={label ?? ""}
      floatingStyles={floatingStyles}
      isPositioned={isPositioned}
      setFloatingRef={setFloatingRef}
      groups={foldedGroups}
      emptySet={allOptions.length === 0}
      isSelected={isSelected}
      exactValue={exactValue}
      highlightedIndex={highlightedIndex}
      keyboardNav={isKeyboardNav}
      onSelect={onSelect}
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
              placeholder: search.placeholder || strings.selectSearchPlaceholder,
              onChange: (next) => {
                setSearchText(next);
                search.onChange?.(next);
                // Typing never highlights; only walking the list does.
                setHighlightedIndex(-1);
                setIsKeyboardNav(false);
              },
              onKeyDown: (event) => {
                handleKeyDown(event);
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
  type DropdownDataProps,
};
