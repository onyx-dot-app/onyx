import type { ReactNode } from "react";
import type {
  ColumnDef,
  SortingState,
  VisibilityState,
} from "@tanstack/react-table";
import type { TableSize } from "@opal/components/table/TableSizeContext";
import type { TableProminence } from "@opal/components/table/TableRow";
import type { IconFunctionComponent } from "@opal/types";
import type { SortDirection } from "@opal/components/table/TableHead";

// ---------------------------------------------------------------------------
// Column width (mirrors useColumnWidths types)
// ---------------------------------------------------------------------------

/** Width config for a data column (participates in proportional distribution). */
export interface DataColumnWidth {
  weight: number;
  minWidth?: number;
}

/** Width config for a fixed column (exact pixels, no proportional distribution). */
export interface FixedColumnWidth {
  fixed: number;
}

export type ColumnWidth = DataColumnWidth | FixedColumnWidth;

// ---------------------------------------------------------------------------
// Column kind discriminant
// ---------------------------------------------------------------------------

export type QualifierContentType = "simple" | "icon" | "image";

export type OnyxColumnKind = "qualifier" | "data" | "display" | "actions";

// ---------------------------------------------------------------------------
// Public columns: plain literals, discriminated on `kind`
// ---------------------------------------------------------------------------

/** The leading cell: a checkbox, icon or image per row. */
export interface TableQualifierColumn<TData> {
  kind: "qualifier";
  /** What the cell shows besides the selection checkbox. @default "simple" */
  content?: QualifierContentType;
  /** The row's icon, for `content: "icon"`. */
  icon?: (row: TData) => IconFunctionComponent;
  /** The row's image URL, for `content: "image"`. */
  imageSrc?: (row: TData) => string;
  /** The row's image alt text, for `content: "image"`. @default "" */
  imageAlt?: (row: TData) => string;
  /** A tinted tile behind the icon or image. @default false */
  background?: boolean;
  /** `"lg"` for avatars, `"md"` for icons. @default "md" */
  iconSize?: "lg" | "md";
}

/** What every data column takes, whatever its value comes from. */
interface TableDataColumnOptions<TData, TValue> {
  kind: "data";
  /** The header label. */
  title: string;
  /** Renders the cell. Left out, the value renders as text. */
  cell?: (value: TValue, row: TData) => ReactNode;
  /** @default true */
  sortable?: boolean;
  /** @default true */
  resizable?: boolean;
  /** Can be hidden from the column-visibility popover. @default true */
  hideable?: boolean;
  /** Replaces the header's sort icon. */
  sortIcon?: (sorted: SortDirection) => IconFunctionComponent;
  /** Share of the free width. @default 20 */
  weight?: number;
  alignment?: ColumnAlignment;
}

/**
 * A data column over one field of the row. `cell` gets that field's type,
 * and the field's value drives sorting and search.
 */
export type TableFieldColumn<TData> = {
  [K in keyof TData & string]: TableDataColumnOptions<TData, TData[K]> & {
    field: K;
    /** Defaults to `field`. */
    id?: string;
    value?: never;
  };
}[keyof TData & string];

/**
 * A data column over a derived value, which drives sorting and search (e.g.
 * a name and an email joined, so either matches).
 */
export interface TableValueColumn<TData> extends TableDataColumnOptions<
  TData,
  TableCellValue
> {
  id: string;
  value: (row: TData) => TableCellValue;
  field?: never;
}

/** What a value column's `value` may return: something sortable and searchable. */
export type TableCellValue = string | number | boolean | null | undefined;

/** A column with no value of its own: a cell rendered from the row. */
export interface TableDisplayColumn<TData> {
  kind: "display";
  id: string;
  /** The header label. */
  title?: string;
  cell: (row: TData) => ReactNode;
  width: ColumnWidth;
  /** @default true */
  hideable?: boolean;
  alignment?: ColumnAlignment;
}

/** The trailing column: per-row actions, and the header's popovers. */
export interface TableActionsColumn<TData> {
  kind: "actions";
  /** The row's action buttons. */
  cell?: (row: TData) => ReactNode;
  /** The column-visibility popover in the header. @default true */
  showColumnVisibility?: boolean;
  /** The sorting popover in the header. @default true */
  showSorting?: boolean;
  /** Footer text for the sorting popover. */
  sortingFooterText?: string;
}

/** One column of a `Table`, told apart by `kind`, like a Dropdown item. */
export type TableColumn<TData> =
  | TableQualifierColumn<TData>
  | TableFieldColumn<TData>
  | TableValueColumn<TData>
  | TableDisplayColumn<TData>
  | TableActionsColumn<TData>;

// ---------------------------------------------------------------------------
// Internal column definitions, resolved from `TableColumn`
// ---------------------------------------------------------------------------

export type ColumnAlignment = "left" | "center" | "right";

interface OnyxColumnBase<TData> {
  kind: OnyxColumnKind;
  /** Stable column identifier (mirrors the TanStack column ID). */
  id: string;
  def: ColumnDef<TData, any>;
  width: ColumnWidth | ((size: TableSize) => ColumnWidth);
}

/** Qualifier column — leading avatar/icon/checkbox column. */
export interface OnyxQualifierColumn<TData> extends OnyxColumnBase<TData> {
  kind: "qualifier";
  alignment?: never;
  /** Content type for body-row `<TableQualifier>`. */
  content: QualifierContentType;
  /** Return the icon component to render for a row (for "icon" content). */
  getContent?: (row: TData) => IconFunctionComponent;
  /** Return the image URL to render for a row (for "image" content). */
  getImageSrc?: (row: TData) => string;
  /** Return the image alt text for a row (for "image" content). @default "" */
  getImageAlt?: (row: TData) => string;
  /** Show a tinted background container behind the content. @default false */
  background?: boolean;
  /** Icon size preset. Use `"lg"` for avatars, `"md"` for regular icons. @default "md" */
  iconSize?: "lg" | "md";
}

/** Data column — accessor-based column with sorting/resizing. */
export interface OnyxDataColumn<TData> extends OnyxColumnBase<TData> {
  kind: "data";
  alignment?: ColumnAlignment;
  /** Override the sort icon for this column. */
  icon?: (sorted: SortDirection) => IconFunctionComponent;
}

/** Display column — non-accessor column with custom rendering. */
export interface OnyxDisplayColumn<TData> extends OnyxColumnBase<TData> {
  kind: "display";
  alignment?: ColumnAlignment;
}

/** Actions column — fixed column with visibility/sorting popovers. */
export interface OnyxActionsColumn<TData> extends OnyxColumnBase<TData> {
  kind: "actions";
  alignment?: never;
  /** Show column visibility popover. @default true */
  showColumnVisibility?: boolean;
  /** Show sorting popover. @default true */
  showSorting?: boolean;
  /** Footer text for the sorting popover. */
  sortingFooterText?: string;
}

/** Discriminated union of all column types. */
export type OnyxColumnDef<TData> =
  | OnyxQualifierColumn<TData>
  | OnyxDataColumn<TData>
  | OnyxDisplayColumn<TData>
  | OnyxActionsColumn<TData>;

// ---------------------------------------------------------------------------
// Server-side pagination / sorting / search
// ---------------------------------------------------------------------------

/** Server-side configuration for DataTable. */
export interface ServerSideConfig {
  /** Total row count from the server. Used to compute page count. */
  totalItems: number;
  /** Whether data is currently being fetched. Shows loading state. */
  isLoading?: boolean;
  /** Fired when sorting state changes. */
  onSortingChange: (sorting: SortingState) => void;
  /** Fired when pagination changes (including page resets from sort/search). */
  onPaginationChange: (pageIndex: number, pageSize: number) => void;
  /** Fired when `query` changes. */
  onQueryChange: (query: string) => void;
}

// ---------------------------------------------------------------------------
// DataTable props
// ---------------------------------------------------------------------------

export interface DataTableDraggableConfig {
  /** Called after a successful reorder with the new ID order and changed positions. */
  onReorder: (
    ids: string[],
    changedOrders: Record<string, number>
  ) => void | Promise<void>;
}

/** Footer configuration. Mode is derived from `selectionBehavior` automatically. */
export interface DataTableFooterConfig {
  /** Handler for the "Clear" button (multi-select only). When omitted, the default clearSelection is used. */
  onClear?: () => void;
  /** Unit label for count pagination, e.g. "users", "documents" (multi-select only). */
  units?: string;
  /** Optional extra element rendered after the summary text, e.g. a download icon (summary mode only). */
  leftExtra?: ReactNode;
}

export interface DataTableProps<TData> {
  /** The rows. */
  items: TData[];
  /** The columns, in order. */
  columns: TableColumn<TData>[];
  /** Extract a unique string ID from each row. Used for stable row identity. */
  getRowId: (row: TData) => string;
  /** The table's accessible name. */
  label?: string;
  /** Rows per page. Set `Infinity` to disable pagination. @default 10 */
  pageSize?: number;
  /** Initial sorting state. */
  initialSorting?: SortingState;
  /** Initial column visibility state. */
  initialColumnVisibility?: VisibilityState;
  /**
   * The selected row IDs (from `getRowId`). Given, the selection is
   * controlled: change it from `onSelectionChange`. Left out, the table
   * keeps its own.
   */
  values?: ReadonlySet<string>;
  /** Called with the next selection. */
  onSelectionChange?: (values: ReadonlySet<string>) => void;
  /** When true AND `values` is non-empty at mount, start in view-selected mode. @default false */
  initialViewSelected?: boolean;
  /** Enable drag-and-drop row reordering. */
  draggable?: DataTableDraggableConfig;
  /** Footer configuration. */
  footer?: DataTableFooterConfig;
  /** Table size variant. @default "lg" */
  size?: TableSize;
  /**
   * The rows' surface: `"primary"` rests on `background-tint-00` (white),
   * `"secondary"` on `background-tint-01` (grey). Every row is an
   * `Interactive.Stateful` surface with hover and selected states.
   *
   * @default "primary"
   */
  prominence?: TableProminence;
  /** Called when a row is clicked (replaces the default selection toggle). */
  onRowClick?: (row: TData) => void;
  getRowLabel?: (row: TData) => string;
  /** Filters the rows to those whose data-column values contain it (case-insensitive). */
  query?: string;
  /**
   * Max height of the scrollable table area. When set, the table body scrolls
   * vertically while the header stays pinned at the top.
   * Accepts a pixel number (e.g. `300`) or a CSS value string (e.g. `"50vh"`).
   */
  height?: number | string;
  /**
   * Enable server-side mode. When provided:
   * - TanStack uses manualPagination/manualSorting/manualFiltering
   * - `items` should contain only the current page's rows
   * - Dragging is automatically disabled
   * - Fires separate callbacks for sorting, pagination, and query changes
   */
  serverSide?: ServerSideConfig;
  /** Content to render inside the table body when there are no rows. */
  emptyState?: React.ReactNode;
  /**
   * Render the header row. Hiding it also hides what lives there: sorting by
   * header click, column resizing, the select-all checkbox, and the actions
   * column's popovers.
   *
   * @default true
   */
  showHeader?: boolean;
}
