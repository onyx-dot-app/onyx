"use client";

import { createContext, useContext } from "react";
import type {
  DropdownKeyOptions,
  ListModel,
} from "@opal/components/dropdown/hooks";
import type {
  DropdownMode,
  DropdownViews,
  DropdownWidth,
} from "@opal/components/dropdown/types";

/**
 * What `Dropdown` shares with its parts. Opal-internal: the input family's
 * engines read it to wire a field they render themselves (a `TagField`),
 * where `Dropdown.Trigger` cannot reach the input. App code uses the
 * composer.
 */
export interface DropdownContextValue {
  /** Prefix for the list's and the rows' element ids. */
  id: string;
  disabled: boolean;
  /** Where the list portals to; `document.body` when left out. */
  container: HTMLElement | null | undefined;
  isOpen: boolean;
  setIsOpen: (open: boolean | ((prev: boolean) => boolean)) => void;
  highlightedIndex: number;
  setHighlightedIndex: (index: number | ((prev: number) => number)) => void;
  isKeyboardNav: boolean;
  setIsKeyboardNav: (isKeyboard: boolean) => void;
  /** The element the list positions against, when it is not the trigger. */
  setAnchorRef: (node: HTMLElement | null) => void;
  /** The element that holds focus and takes the keyboard. */
  setTriggerRef: (node: HTMLElement | null) => void;
  /** Forget a trigger on unmount, if it is the current one. */
  releaseTriggerRef: (node: HTMLElement | null) => void;
  /** Every mounted trigger counts as inside for outside-click dismissal. */
  registerTrigger: (node: HTMLElement) => void;
  unregisterTrigger: (node: HTMLElement) => void;
  focusTrigger: () => void;
  floatingRef: React.RefObject<HTMLDivElement | null>;
  setFloatingRef: (node: HTMLDivElement | null) => void;
  floatingStyles: React.CSSProperties;
  isPositioned: boolean;
  /** The edge the list grows from, as floating-ui placed it. */
  anchoredEdge: "top" | "bottom";
  /** Filled by `Dropdown.Data`; read by the keyboard handler at event time. */
  listRef: React.RefObject<ListModel>;
  /** Picker or menu, as `Dropdown.Data` declared it. */
  mode: DropdownMode;
  setMode: (mode: DropdownMode) => void;
  /** The width the view on top asks for, if any. */
  setViewWidth: (width: DropdownWidth | undefined) => void;
  /** The highlighted stop's element id, for `aria-activedescendant`. */
  activeId: string | undefined;
  setActiveId: (id: string | undefined) => void;
  handleKeyDown: (
    event: React.KeyboardEvent<HTMLElement>,
    options: DropdownKeyOptions
  ) => void;
  /**
   * The attributes a trigger carries: the list it controls, whether it is
   * open, and the highlighted stop, plus the keyboard handler. A picker's
   * trigger is a combobox; a menu's keeps its own role. A type-in trigger
   * also announces list autocomplete.
   */
  getTriggerProps: (options: {
    typeIn: boolean;
    /** The trigger is a `<button>`: it keeps its role and its name. */
    nativeButton?: boolean;
  }) => DropdownTriggerProps;
}

export interface DropdownTriggerProps {
  role: "combobox" | undefined;
  "aria-expanded": boolean;
  "aria-haspopup": "listbox" | "menu";
  "aria-controls": string;
  "aria-activedescendant": string | undefined;
  "aria-autocomplete": "list" | undefined;
  onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void;
}

export const DropdownContext = createContext<DropdownContextValue | null>(null);

export function useDropdownContext(): DropdownContextValue {
  const context = useContext(DropdownContext);
  if (!context) {
    throw new Error("Dropdown parts must be rendered inside <Dropdown>.");
  }
  return context;
}

export const DropdownViewsContext = createContext<DropdownViews | null>(null);

/**
 * The view stack, for a control rendered inside the list (a button in a
 * custom row): push a view, go back one, or close. Row handlers get the
 * same object as an argument.
 */
export function useDropdownViews(): DropdownViews {
  const views = useContext(DropdownViewsContext);
  if (!views) {
    throw new Error(
      "useDropdownViews must be called inside a Dropdown.Data row."
    );
  }
  return views;
}
