"use client";

import { useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  type Table,
  type ColumnDef,
  type RowData,
  type SortingState,
  type RowSelectionState,
  type ColumnSizingState,
  type PaginationState,
  type ColumnResizeMode,
  type TableOptions,
  type VisibilityState,
} from "@tanstack/react-table";

// ---------------------------------------------------------------------------
// Exported types
// ---------------------------------------------------------------------------

export type OnyxSortDirection = "none" | "ascending" | "descending";
export type OnyxSelectionState = "none" | "partial" | "all";

// ---------------------------------------------------------------------------
// Exported utility
// ---------------------------------------------------------------------------

/**
 * Convert a TanStack sort direction to an Onyx sort direction string.
 *
 * This is a **named export** (not on the return object) because it is used
 * statically inside JSX header loops, not tied to hook state.
 */
export function toOnyxSortDirection(
  dir: false | "asc" | "desc"
): OnyxSortDirection {
  if (dir === "asc") return "ascending";
  if (dir === "desc") return "descending";
  return "none";
}

// ---------------------------------------------------------------------------
// Hook options & return types
// ---------------------------------------------------------------------------

/** Keys managed internally — callers cannot override these via `tableOptions`. */
type ManagedKeys =
  | "data"
  | "columns"
  | "state"
  | "onSortingChange"
  | "onRowSelectionChange"
  | "onColumnSizingChange"
  | "onColumnVisibilityChange"
  | "onPaginationChange"
  | "getCoreRowModel"
  | "getSortedRowModel"
  | "getPaginationRowModel"
  | "columnResizeMode"
  | "enableRowSelection";

/**
 * Options accepted by {@link useDataTable}.
 *
 * Only `data` and `columns` are required — everything else has sensible defaults.
 */
interface UseDataTableOptions<TData extends RowData> {
  /** The row data array. */
  data: TData[];
  /** TanStack column definitions. */
  columns: ColumnDef<TData, any>[];
  /** Rows per page. Set `Infinity` to disable pagination. @default 10 */
  pageSize?: number;
  /** Whether rows can be selected. @default true */
  enableRowSelection?: boolean;
  /** Whether columns can be resized. @default true */
  enableColumnResizing?: boolean;
  /** Resize strategy. @default "onChange" */
  columnResizeMode?: ColumnResizeMode;
  /** Initial sorting state. @default [] */
  initialSorting?: SortingState;
  /** Initial column visibility state. @default {} */
  initialColumnVisibility?: VisibilityState;
  /** Escape-hatch: extra options spread into `useReactTable`. Managed keys are excluded. */
  tableOptions?: Partial<Omit<TableOptions<TData>, ManagedKeys>>;
}

/**
 * Values returned by {@link useDataTable}.
 */
interface UseDataTableReturn<TData extends RowData> {
  /** Full TanStack table instance for rendering. */
  table: Table<TData>;

  // Pagination (1-based, matching Onyx Footer)
  /** Current page number (1-based). */
  currentPage: number;
  /** Total number of pages. */
  totalPages: number;
  /** Total number of rows. */
  totalItems: number;
  /** Rows per page. */
  pageSize: number;
  /** Navigate to a page (1-based, clamped to valid range). */
  setPage: (page: number) => void;
  /** Whether pagination is active (pageSize is finite). */
  isPaginated: boolean;

  // Selection (pre-computed for Onyx Footer)
  /** Aggregate selection state for the current page. */
  selectionState: OnyxSelectionState;
  /** Number of selected rows. */
  selectedCount: number;
  /** Whether every row on the current page is selected. */
  isAllPageRowsSelected: boolean;
  /** Deselect all rows. */
  clearSelection: () => void;
  /** Select or deselect all rows on the current page. */
  toggleAllPageRowsSelected: (selected: boolean) => void;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Wraps TanStack `useReactTable` with Onyx-specific defaults and derived
 * state so that consumers only need to provide `data` + `columns`.
 *
 * @example
 * ```tsx
 * const {
 *   table, currentPage, totalPages, setPage, pageSize,
 *   selectionState, selectedCount, clearSelection,
 * } = useDataTable({ data: rows, columns });
 * ```
 */
export default function useDataTable<TData extends RowData>(
  options: UseDataTableOptions<TData>
): UseDataTableReturn<TData> {
  const {
    data,
    columns,
    pageSize: pageSizeOption = 10,
    enableRowSelection = true,
    enableColumnResizing = true,
    columnResizeMode = "onChange",
    initialSorting = [],
    initialColumnVisibility = {},
    tableOptions,
  } = options;

  // ---- internal state -----------------------------------------------------
  const [sorting, setSorting] = useState<SortingState>(initialSorting);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>({});
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(
    initialColumnVisibility
  );
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: pageSizeOption,
  });

  // ---- TanStack table instance --------------------------------------------
  const table = useReactTable({
    data,
    columns,
    state: {
      sorting,
      rowSelection,
      columnSizing,
      columnVisibility,
      pagination,
    },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    onColumnSizingChange: setColumnSizing,
    onColumnVisibilityChange: setColumnVisibility,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    columnResizeMode,
    enableRowSelection,
    enableColumnResizing,
    ...tableOptions,
  });

  // ---- derived values -----------------------------------------------------
  const isAllPageRowsSelected = table.getIsAllPageRowsSelected();
  const isSomePageRowsSelected = table.getIsSomePageRowsSelected();

  const selectionState: OnyxSelectionState = isAllPageRowsSelected
    ? "all"
    : isSomePageRowsSelected
      ? "partial"
      : "none";

  const selectedCount = Object.keys(rowSelection).length;
  const totalPages = table.getPageCount();
  const currentPage = pagination.pageIndex + 1;
  const totalItems = data.length;
  const isPaginated = isFinite(pageSizeOption);

  // ---- actions ------------------------------------------------------------
  const setPage = (page: number) => {
    const clamped = Math.max(1, Math.min(page, totalPages));
    setPagination((prev) => ({ ...prev, pageIndex: clamped - 1 }));
  };

  const clearSelection = () => {
    table.resetRowSelection();
  };

  const toggleAllPageRowsSelected = (selected: boolean) => {
    table.toggleAllPageRowsSelected(selected);
  };

  return {
    table,
    currentPage,
    totalPages,
    totalItems,
    pageSize: pageSizeOption,
    setPage,
    isPaginated,
    selectionState,
    selectedCount,
    isAllPageRowsSelected,
    clearSelection,
    toggleAllPageRowsSelected,
  };
}
