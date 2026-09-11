"use client";

import { createContext, useContext, type ReactNode } from "react";

/**
 * Labels Opal renders itself. Hosts translate them via `OpalStringsProvider`.
 */
export type OpalStrings = {
  close: string;
  loading: string;
  loadingPage: string;
  copy: string;
  copied: string;
  copyCode: string;
  clear: string;
  attachFile: string;
  clearFile: string;
  clearFilter: string;
  date: string;
  dateRange: string;
  dateRangeOneDay: string;
  dateRangeSevenDays: string;
  dateRangeOneMonth: string;
  dateRangeThreeMonths: string;
  dateRangeCustom: string;
  dateRangeChooseCustom: string;
  dateRangeCustomRange: (from: string, to: string) => string;
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
  image: string;
  imageUpload: string;
  imageEdit: string;
  imageRemove: string;
  imageDropRejected: string;
  comboBoxOpen: string;
  comboBoxClose: string;
  comboBoxNoOptions: string;
  comboBoxOtherOptions: string;
  comboBoxCreate: string;
  comboBoxCreateOption: (prefix: string, value: string) => string;
  multiSelectNoResults: string;
  multiSelectEmptyTitle: string;
  multiSelectEmptyDescription: string;
  keyValueKey: string;
  keyValueValue: string;
  keyValueAddLine: string;
  keyValueAddPair: (keyTitle: string, valueTitle: string) => string;
  keyValueEmpty: string;
  keyValueEmptyKey: string;
  keyValueDuplicateKey: string;
  keyValueEmptySummary: (count: number) => string;
  keyValueDuplicateSummary: (count: number) => string;
  keyValueValidationSummary: (count: number) => string;
  keyValueGroup: (keyTitle: string, valueTitle: string) => string;
  keyValueInput: (label: string, index: number) => string;
  keyValuePairFallback: string;
  keyValueRemovePair: (label: string, index: number) => string;

  /** Locale digits, no grouping, for the counts Opal renders itself (footer range, page numbers). */
  formatNumber: (value: number) => string;
  /** Inverse of formatNumber for typed input: a whole number in the locale digits (ASCII always accepted), else null. */
  parseNumber: (text: string) => number | null;
  /** Table footer summary, e.g. "Showing 1~10 of 22", as text chunks around the two styled nodes. */
  showing: (range: ReactNode, total: ReactNode) => ReactNode;
  /** Pagination count summary, e.g. "1~10 of 22", same chunk shape as `showing`. */
  rangeOfTotal: (range: ReactNode, total: ReactNode) => ReactNode;
};

export const defaultOpalStrings: OpalStrings = {
  close: "Close",
  loading: "Loading",
  loadingPage: "Loading …",
  copy: "Copy",
  copied: "Copied!",
  copyCode: "Copy code",
  clear: "Clear",
  attachFile: "Attach file",
  clearFile: "Clear file",
  clearFilter: "Clear filter",
  date: "Date",
  dateRange: "Date range",
  dateRangeOneDay: "1D",
  dateRangeSevenDays: "7D",
  dateRangeOneMonth: "1M",
  dateRangeThreeMonths: "3M",
  dateRangeCustom: "Custom",
  dateRangeChooseCustom: "Choose a custom range",
  dateRangeCustomRange: (from, to) => `Custom range: ${from} to ${to}`,
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
  image: "Image",
  imageUpload: "Upload image",
  imageEdit: "Edit image",
  imageRemove: "Remove image",
  imageDropRejected: "File rejected",
  comboBoxOpen: "Open dropdown",
  comboBoxClose: "Close dropdown",
  comboBoxNoOptions: "No options found",
  comboBoxOtherOptions: "Other options",
  comboBoxCreate: "Create",
  comboBoxCreateOption: (prefix, value) => `${prefix} "${value}"`,
  multiSelectNoResults: "No matching options",
  multiSelectEmptyTitle: "Nothing selected yet",
  multiSelectEmptyDescription: "Search above to add items",
  keyValueKey: "Key",
  keyValueValue: "Value",
  keyValueAddLine: "Add Line",
  keyValueAddPair: (keyTitle, valueTitle) =>
    `Add ${keyTitle} and ${valueTitle} pair`,
  keyValueEmpty: "No items added yet.",
  keyValueEmptyKey: "Key cannot be empty",
  keyValueDuplicateKey: "Duplicate key",
  keyValueEmptySummary: (count) =>
    count === 1 ? "1 empty key found" : `${count} empty keys found`,
  keyValueDuplicateSummary: (count) =>
    count === 1 ? "1 duplicate key found" : `${count} duplicate keys found`,
  keyValueValidationSummary: (count) =>
    count === 1
      ? "1 validation error found"
      : `${count} validation errors found`,
  keyValueGroup: (keyTitle, valueTitle) =>
    `${keyTitle} and ${valueTitle} pairs`,
  keyValueInput: (label, index) => `${label} ${index}`,
  keyValuePairFallback: "key-value",
  keyValueRemovePair: (label, index) => `Remove ${label} pair ${index}`,
  formatNumber: (value) => String(value),
  parseNumber: (text) => (/^\d+$/.test(text) ? Number(text) : null),
  showing: (range, total) => ["Showing ", range, " of ", total],
  rangeOfTotal: (range, total) => [range, " of ", total],
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
