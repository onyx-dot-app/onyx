import type { IconFunctionComponent, RichStr } from "@opal/types";

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

interface DropdownRowBase {
  /** Further text a search matches, such as an identifier the title prettifies. */
  keywords?: string[];
  /** A disabled row shows but is not a keyboard stop and ignores clicks. */
  disabled?: boolean;
}

/** A selectable row of a picker. `value` identifies it; `title` is what it shows. */
export interface DropdownOption extends DropdownRowBase {
  kind: "option";
  value: string;
  title: string;
  description?: string | RichStr;
  /** Muted text beside the title in the list, like "(Default)". */
  suffix?: string;
  icon?: IconFunctionComponent;
}

/**
 * A row that runs a command: `onSelect`, or `href` to follow (a real link,
 * so middle-click and copy-link work), or both. The dropdown closes after
 * it unless `keepOpen` is set or the handler pushed a view.
 */
export type DropdownAction = DropdownRowBase & {
  kind: "action";
  id: string;
  title: string;
  description?: string | RichStr;
  icon?: IconFunctionComponent;
  /** A destructive command: the row reads in the danger colour. */
  danger?: boolean;
  keepOpen?: boolean;
  /**
   * The row leads to a view: it shows a trailing chevron, ArrowRight
   * activates it too, and the list stays open after it. An affordance only;
   * `onSelect` decides whether to push.
   */
  opensView?: boolean;
} & (
    | {
        href: string;
        /** Link target, with `href`. */
        target?: string;
        onSelect?: (views: DropdownViews) => void;
      }
    | { href?: never; target?: never; onSelect: (views: DropdownViews) => void }
  );

/** A row with a switch. Activating it flips `checked`; the dropdown stays open. */
export interface DropdownToggle extends DropdownRowBase {
  kind: "toggle";
  id: string;
  title: string;
  description?: string | RichStr;
  icon?: IconFunctionComponent;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}

/**
 * What the dropdown hands a custom row. Spread `props` onto the row's root
 * element: they keep it in the keyboard walk, under `aria-activedescendant`
 * and in scroll-into-view, and route a click to `onActivate`. Controls
 * inside the row stop propagation themselves.
 */
export interface DropdownRowState {
  /** The keyboard stop is on this row: render it as hovered. */
  highlighted: boolean;
  props: DropdownRowProps;
}

export interface DropdownRowProps {
  id: string;
  role: "option" | "menuitem";
  "aria-selected"?: boolean;
  "aria-disabled"?: boolean;
  "data-index": number;
  tabIndex: -1;
  onClick: (event: React.MouseEvent) => void;
  onMouseDown: (event: React.MouseEvent) => void;
}

/**
 * A row rendered by the caller. Enter runs `onActivate` and ArrowRight
 * `onSecondary` (a control at the row's end). Searchable by `keywords`
 * only: the dropdown cannot read what the row shows.
 */
export interface DropdownCustom extends DropdownRowBase {
  kind: "custom";
  id: string;
  onActivate?: (views: DropdownViews) => void;
  onSecondary?: (views: DropdownViews) => void;
  /** Stay open after `onActivate`. */
  keepOpen?: boolean;
  /** As on an action: a trailing-chevron row that ArrowRight activates. The caller renders the chevron. */
  opensView?: boolean;
  render: (row: DropdownRowState) => React.ReactNode;
}

/** The rows a menu (no `value`) may hold. */
export type DropdownMenuRow = DropdownAction | DropdownToggle | DropdownCustom;

/** Every row kind; `option` is a picker's. */
export type DropdownRow = DropdownOption | DropdownMenuRow;

// ---------------------------------------------------------------------------
// Groups and items
// ---------------------------------------------------------------------------

/**
 * A divider with the rows under it, like an `<optgroup>`. A separator line
 * sits above it, carrying `title` when there is one. A titled group may be
 * `foldable`: its rows fold behind the title. It starts closed unless it
 * holds the selection, opens while a search is on, and a click on the title
 * toggles it either way.
 */
export type DropdownGroup<Row extends DropdownRow = DropdownRow> =
  | { kind: "group"; title: string; foldable?: boolean; items: Row[] }
  | { kind: "group"; title?: undefined; foldable?: never; items: Row[] };

/**
 * One entry of a picker's list. Loose rows and groups sit in any order,
 * like `<option>`s beside `<optgroup>`s: a loose row renders plain, and a
 * run of them after a group gets a plain line above it.
 */
export type DropdownItem = DropdownRow | DropdownGroup;

/** One entry of a menu's list: no `option` rows, since nothing is selected. */
export type DropdownMenuItem = DropdownMenuRow | DropdownGroup<DropdownMenuRow>;

/** Picker (`listbox`, something is selected) or menu (`menu`, commands). */
export type DropdownMode = "picker" | "menu";

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

/** A search field pinned above the rows. `onChange` reports the text, and `""` when the rows leave. */
export interface DropdownSearch {
  placeholder: string;
  onChange?: (query: string) => void;
}

/**
 * A secondary view: rows that replace the list's rows in place. Nothing is
 * laid out for it: a way back is a row that calls `pop`. Its search is its
 * own and never reaches the rows above or below it on the stack.
 */
export interface DropdownView {
  /** Identifies the view on the stack; its depth when left out. */
  key?: string;
  items: DropdownMenuItem[];
  search?: DropdownSearch;
}

/**
 * The view stack, handed to every row handler and to `useDropdownViews()`
 * inside the list. Any row or nested control pushes a view, under any
 * logic it likes.
 */
export interface DropdownViews {
  /** Replace the rows with `view`, in place. The list stays open. */
  push: (view: DropdownView) => void;
  /** Back one view. Nothing happens at the root. */
  pop: () => void;
  close: () => void;
}

// ---------------------------------------------------------------------------
// Internal list model
// ---------------------------------------------------------------------------

/**
 * The list's render unit: a run of rows. Each group is one, and each run of
 * loose rows between groups is one too. A separator line renders between
 * consecutive runs, titled when the run below it has a title.
 */
export interface RowGroup {
  /** Stable within the list: two groups may share a title, never a key. */
  key: string;
  title?: string;
  rows: DropdownRow[];
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
  | { kind: "row"; row: DropdownRow; group: RowGroup }
  | { kind: "group"; group: RowGroup }
  | { kind: "create"; text: string };
