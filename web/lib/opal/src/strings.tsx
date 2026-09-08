"use client";

import { createContext, useContext, type ReactNode } from "react";

/**
 * Labels Opal renders itself. Hosts translate them via `OpalStringsProvider`.
 */
export interface OpalStrings {
  close: string;
  loading: string;
  loadingPage: string;
  copy: string;
  copied: string;
  copyCode: string;
  clear: string;
  clearFilter: string;
  date: string;
  time: string;
  edit: string;
  search: string;
  progress: string;
  remove: string;
  removeItem: (title: string) => string;
  showFullMessage: string;
  selectAnOption: string;
  openCalendar: string;
  month: string;
  day: string;
  year: string;
  hours: string;
  minutes: string;
  seconds: string;
  showPassword: string;
  hidePassword: string;
  valueCannotBeRevealed: string;
  scrollTabsLeft: string;
  scrollTabsRight: string;
  previousPage: string;
  nextPage: string;
  goToPage: string;
  sort: string;
  sortBy: string;
  manualOrdering: string;
  sortingOrder: string;
  ascending: string;
  descending: string;
  columns: string;
  shownColumns: string;
  alwaysShown: string;
  dragToReorder: string;
  viewSelected: string;
  deselectAll: string;
  selectItemsToContinue: string;
  selectAnItemToContinue: string;
  singleItemSelected: string;
  selectedItemCount: (count: number) => string;
  /** Table footer summary, e.g. "Showing 1~10 of 22". Both arguments are styled inline nodes. */
  showing: (range: ReactNode, total: ReactNode) => ReactNode;
}

export const defaultOpalStrings: OpalStrings = {
  close: "Close",
  loading: "Loading",
  loadingPage: "Loading …",
  copy: "Copy",
  copied: "Copied!",
  copyCode: "Copy code",
  clear: "Clear",
  clearFilter: "Clear filter",
  date: "Date",
  time: "Time",
  edit: "Edit",
  search: "Search...",
  progress: "Progress",
  remove: "Remove",
  removeItem: (title) => `Remove ${title}`,
  showFullMessage: "Show the full message",
  selectAnOption: "Select an option",
  openCalendar: "Open calendar",
  month: "Month",
  day: "Day",
  year: "Year",
  hours: "Hours",
  minutes: "Minutes",
  seconds: "Seconds",
  showPassword: "Show password",
  hidePassword: "Hide password",
  valueCannotBeRevealed: "Value cannot be revealed",
  scrollTabsLeft: "Scroll tabs left",
  scrollTabsRight: "Scroll tabs right",
  previousPage: "Previous page",
  nextPage: "Next page",
  goToPage: "Go to page",
  sort: "Sort",
  sortBy: "Sort by",
  manualOrdering: "Manual Ordering",
  sortingOrder: "Sorting Order",
  ascending: "Ascending",
  descending: "Descending",
  columns: "Columns",
  shownColumns: "Shown Columns",
  alwaysShown: "Always Shown",
  dragToReorder: "Drag to reorder",
  viewSelected: "View selected",
  deselectAll: "Deselect all",
  selectItemsToContinue: "Select items to continue",
  selectAnItemToContinue: "Select an item to continue",
  singleItemSelected: "Item selected",
  selectedItemCount: (count) =>
    `${count} item${count !== 1 ? "s" : ""} selected`,
  showing: (range, total) => (
    <>
      Showing {range} of {total}
    </>
  ),
};

const OpalStringsContext = createContext<OpalStrings>(defaultOpalStrings);

interface OpalStringsProviderProps {
  strings: OpalStrings;
  children: ReactNode;
}

export function OpalStringsProvider({
  strings,
  children,
}: OpalStringsProviderProps) {
  return (
    <OpalStringsContext.Provider value={strings}>
      {children}
    </OpalStringsContext.Provider>
  );
}

export function useOpalStrings(): OpalStrings {
  return useContext(OpalStringsContext);
}
