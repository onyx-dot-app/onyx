import type { ReactNode } from "react";
import type {
  ColumnDef,
  SortingState,
  VisibilityState,
} from "@tanstack/react-table";
import type { TableSize } from "@opal/components/table/TableSizeContext";
import type { TableVariant } from "@opal/components/table/TableElement";
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

export type QualifierContentType =
  | "icon"
  | "simple"
  | "image"
  | "avatar-icon"
  | "avatar-user";

export type OnyxColumnKind = "qualifier" | "data" | "display" | "actions";

// ---------------------------------------------------------------------------
// Column definitions (discriminated union on `kind`)
// ---------------------------------------------------------------------------

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
  /** Content type for body-row `<TableQualifier>`. */
  content: QualifierContentType;
  /** Content type for the header `<TableQualifier>`. @default "simple" */
  headerContentType?: QualifierContentType;
  /** Extract initials from a row (for "avatar-user" content). */
  getInitials?: (row: TData) => string;
  /** Extract icon from a row (for "icon" / "avatar-icon" content). */
  getIcon?: (row: TData) => IconFunctionComponent;
  /** Extract image src from a row (for "image" content). */
  getImageSrc?: (row: TData) => string;
  /** Whether to show selection checkboxes on the qualifier. @default true */
  selectable?: boolean;
  /** Whether to render qualifier content in the header. @default true */
  header?: boolean;
}

/** Data column — accessor-based column with sorting/resizing. */
export interface OnyxDataColumn<TData> extends OnyxColumnBase<TData> {
  kind: "data";
  /** Override the sort icon for this column. */
  icon?: (sorted: SortDirection) => IconFunctionComponent;
}

/** Display column — non-accessor column with custom rendering. */
export interface OnyxDisplayColumn<TData> extends OnyxColumnBase<TData> {
  kind: "display";
}

/** Actions column — fixed column with visibility/sorting popovers. */
export interface OnyxActionsColumn<TData> extends OnyxColumnBase<TData> {
  kind: "actions";
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
  /** Fired when searchTerm changes. */
  onSearchTermChange: (searchTerm: string) => void;
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
  /** Row data array. */
  data: TData[];
  /** Column definitions created via `createTableColumns()`. */
  columns: OnyxColumnDef<TData>[];
  /** Extract a unique string ID from each row. Used for stable row identity. */
  getRowId: (row: TData) => string;
  /** Rows per page. Set `Infinity` to disable pagination. @default 10 */
  pageSize?: number;
  /** Initial sorting state. */
  initialSorting?: SortingState;
  /** Initial column visibility state. */
  initialColumnVisibility?: VisibilityState;
  /** Enable drag-and-drop row reordering. */
  draggable?: DataTableDraggableConfig;
  /** Footer configuration. */
  footer?: DataTableFooterConfig;
  /** Table size variant. @default "lg" */
  size?: TableSize;
  /** Visual row variant. @default "cards" */
  variant?: TableVariant;
  /** Called whenever the set of selected row IDs changes. Receives IDs produced by `getRowId`. */
  onSelectionChange?: (selectedIds: string[]) => void;
  /** Called when a row is clicked (replaces the default selection toggle). */
  onRowClick?: (row: TData) => void;
  /** Search term for global text filtering. When provided, rows are filtered
   *  to those containing the term in any accessor column value (case-insensitive). */
  searchTerm?: string;
  /**
   * Max height of the scrollable table area. When set, the table body scrolls
   * vertically while the header stays pinned at the top.
   * Accepts a pixel number (e.g. `300`) or a CSS value string (e.g. `"50vh"`).
   */
  height?: number | string;
  /** Background color for the sticky header row, preventing rows from showing
   *  through when scrolling. Accepts any CSS color value. */
  headerBackground?: string;
  /**
   * Enable server-side mode. When provided:
   * - TanStack uses manualPagination/manualSorting/manualFiltering
   * - `data` should contain only the current page's rows
   * - Dragging is automatically disabled
   * - Fires separate callbacks for sorting, pagination, and search changes
   */
  serverSide?: ServerSideConfig;
  /** Content to render inside the table body when there are no rows. */
  emptyState?: React.ReactNode;
}
