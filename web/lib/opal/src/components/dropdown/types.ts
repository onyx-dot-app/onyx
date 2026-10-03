import type { IconFunctionComponent, RichStr } from "@opal/types";

// ---------------------------------------------------------------------------
// Items
// ---------------------------------------------------------------------------

/** A selectable row. `value` identifies it; `title` is what the row shows. */
export interface DropdownOption {
  kind: "option";
  value: string;
  title: string;
  /** Further text a search matches, such as an identifier the title prettifies. */
  keywords?: string[];
  description?: string | RichStr;
  /** Muted text beside the title in the list, like "(Default)". */
  suffix?: string;
  icon?: IconFunctionComponent;
  disabled?: boolean;
}

/**
 * A divider with the rows under it, like an `<optgroup>`. A separator line
 * sits above it, carrying `title` when there is one. A titled group may be
 * `foldable`: its rows fold behind the title. It starts closed unless it
 * holds the selection, opens while a search is on, and a click on the title
 * toggles it either way.
 */
export type DropdownGroup =
  | { kind: "group"; title: string; foldable?: boolean; items: DropdownOption[] }
  | { kind: "group"; title?: undefined; foldable?: never; items: DropdownOption[] };

/**
 * One entry of the list. Loose options and groups sit in any order, like
 * `<option>`s beside `<optgroup>`s: a loose option renders as a plain row,
 * and a run of them after a group gets a plain line above it.
 */
export type DropdownItem = DropdownOption | DropdownGroup;

// ---------------------------------------------------------------------------
// Internal list model
// ---------------------------------------------------------------------------

/**
 * The list's render unit: a run of rows. Each group is one, and each run of
 * loose options between groups is one too. A separator line renders between
 * consecutive runs, titled when the run below it has a title.
 */
export interface OptionGroup {
  title?: string;
  options: DropdownOption[];
  /** The rows fold behind the title. */
  foldable?: boolean;
  /**
   * Render-only: the group is folded. Its rows stay in the list so the fold
   * can animate closed, but they leave the keyboard walk.
   */
  folded?: boolean;
}

/**
 * What the keyboard walks, in render order: the create row when shown, then
 * each foldable group's title (a stop of its own: Enter toggles it) and the
 * rows. The list renders in this exact order, so `highlightedIndex`
 * addresses the same stop in both.
 */
export type NavItem =
  | { kind: "option"; option: DropdownOption }
  | { kind: "group"; group: OptionGroup }
  | { kind: "create"; text: string };
