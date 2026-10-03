"use client";

import { createContext, useContext } from "react";
import type { ListModel } from "@opal/components/dropdown/hooks";

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
  focusTrigger: () => void;
  floatingRef: React.RefObject<HTMLDivElement | null>;
  setFloatingRef: (node: HTMLDivElement | null) => void;
  floatingStyles: React.CSSProperties;
  isPositioned: boolean;
  /** Filled by `Dropdown.Data`; read by the keyboard handler at event time. */
  listRef: React.RefObject<ListModel>;
  /** The highlighted stop's element id, for `aria-activedescendant`. */
  activeId: string | undefined;
  setActiveId: (id: string | undefined) => void;
  handleKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void;
  /**
   * The attributes a trigger carries: its combobox role, the list it
   * controls and the highlighted stop, plus the keyboard handler. A
   * type-in trigger also announces list autocomplete.
   */
  getTriggerProps: (options: { typeIn: boolean }) => DropdownTriggerProps;
}

export interface DropdownTriggerProps {
  role: "combobox";
  "aria-expanded": boolean;
  "aria-haspopup": "listbox";
  "aria-controls": string;
  "aria-activedescendant": string | undefined;
  "aria-autocomplete": "list" | undefined;
  onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void;
}

export const DropdownContext = createContext<DropdownContextValue | null>(
  null
);

export function useDropdownContext(): DropdownContextValue {
  const context = useContext(DropdownContext);
  if (!context) {
    throw new Error("Dropdown parts must be rendered inside <Dropdown>.");
  }
  return context;
}
