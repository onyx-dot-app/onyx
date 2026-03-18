"use client";
"use no memo";

import { useState, useEffect, useMemo, useRef } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  getFilteredRowModel,
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
// Global filter value (combines view-mode + text search)
// ---------------------------------------------------------------------------

interface GlobalFilterValue {
  selectedIds: Set<string> | null;
  searchTerm: string;
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
  | "onGlobalFilterChange"
  | "getCoreRowModel"
  | "getSortedRowModel"
  | "getPaginationRowModel"
  | "getFilteredRowModel"
  | "globalFilterFn"
  | "columnResizeMode"
  | "enableRowSelection"
  | "enableColumnResizing"
  | "getRowId";

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
  /** Stable row identity function. TanStack tracks selection by ID instead of array index. */
  getRowId: TableOptions<TData>["getRowId"];
  /** Resize strategy. @default "onChange" */
  columnResizeMode?: ColumnResizeMode;
  /** Initial sorting state. @default [] */
  initialSorting?: SortingState;
  /** Initial column visibility state. @default {} */
  initialColumnVisibility?: VisibilityState;
  /** Called whenever the set of selected row IDs changes. */
  onSelectionChange?: (selectedIds: string[]) => void;
  /** Search term for global text filtering. Rows are filtered to those containing
   *  the term in any accessor column value (case-insensitive). */
  searchTerm?: string;
  /** Server-side configuration. When provided, enables manual pagination/sorting/filtering. */
  serverSide?: {
    totalItems: number;
    onSortingChange: (sorting: SortingState) => void;
    onPaginationChange: (pageIndex: number, pageSize: number) => void;
    onSearchTermChange: (searchTerm: string) => void;
  };
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
  /** IDs of currently selected rows (derived from `getRowId`). */
  selectedRowIds: string[];
  /** Deselect all rows. */
  clearSelection: () => void;
  /** Select or deselect all rows on the current page. */
  toggleAllPageRowsSelected: (selected: boolean) => void;
  /** Select or deselect all rows across all pages. */
  toggleAllRowsSelected: (selected: boolean) => void;
  /** Whether every row across all pages is selected. */
  isAllRowsSelected: boolean;

  // View-mode (filter to selected rows)
  /** Whether the table is currently filtered to show only selected rows. */
  isViewingSelected: boolean;
  /** Enter view mode — freeze the current selection as a filter. */
  enterViewMode: () => void;
  /** Exit view mode — remove the selection filter. */
  exitViewMode: () => void;
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
    getRowId,
    onSelectionChange,
    searchTerm,
    serverSide,
    tableOptions,
  } = options;

  const isServerSide = !!serverSide;

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
  /** Combined global filter: view-mode (selected IDs) + text search. */
  const [globalFilter, setGlobalFilter] = useState<GlobalFilterValue>({
    selectedIds: null,
    searchTerm: "",
  });

  // ---- sync pageSize prop to internal state --------------------------------
  useEffect(() => {
    setPagination((prev) => ({
      ...prev,
      pageSize: pageSizeOption,
      pageIndex: 0,
    }));
  }, [pageSizeOption]);

  // ---- sync external searchTerm prop into combined filter state ------------
  // (client-side only — server-side uses separate callbacks instead)
  const preSearchPageRef = useRef<number>(0);

  useEffect(() => {
    if (isServerSide) return;
    const term = searchTerm ?? "";
    const wasSearching = !!globalFilter.searchTerm;

    if (!wasSearching && term) {
      // Entering search — save current page, reset to 0
      preSearchPageRef.current = pagination.pageIndex;
      setPagination((p) => ({ ...p, pageIndex: 0 }));
    } else if (wasSearching && !term) {
      // Clearing search — restore saved page
      setPagination((p) => ({ ...p, pageIndex: preSearchPageRef.current }));
    }

    setGlobalFilter((prev) => ({ ...prev, searchTerm: term }));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Intentionally
    // omits `globalFilter` and `pagination.pageIndex`: we only read snapshot
    // values to detect the search enter/clear transition, not to react to
    // every filter or page change.
  }, [searchTerm, isServerSide]);

  // ---- server-side: 3 separate callbacks -----------------------------------
  // Single ref for the whole serverSide config — prevents effects from
  // re-firing when the consumer passes an inline object each render.
  const serverSideRef = useRef(serverSide);
  serverSideRef.current = serverSide;

  useEffect(() => {
    if (!isServerSide) return;
    serverSideRef.current!.onSortingChange(sorting);
  }, [sorting, isServerSide]);

  useEffect(() => {
    if (!isServerSide) return;
    serverSideRef.current!.onPaginationChange(
      pagination.pageIndex,
      pagination.pageSize
    );
  }, [pagination.pageIndex, pagination.pageSize, isServerSide]);

  useEffect(() => {
    if (!isServerSide) return;
    setPagination((p) => ({ ...p, pageIndex: 0 }));
    serverSideRef.current!.onSearchTermChange(searchTerm ?? "");
  }, [searchTerm, isServerSide]);

  // ---- TanStack table instance --------------------------------------------
  const serverPageCount = isServerSide
    ? isFinite(pagination.pageSize) && pagination.pageSize > 0
      ? Math.ceil((serverSide!.totalItems || 0) / pagination.pageSize)
      : 1
    : undefined;

  const tableOpts: TableOptions<TData> = {
    data,
    columns,
    getRowId,
    state: {
      sorting,
      rowSelection,
      columnSizing,
      columnVisibility,
      pagination,
      ...(isServerSide ? {} : { globalFilter }),
    },
    onSortingChange: isServerSide
      ? (updater) => {
          setSorting(updater);
          setPagination((p) => ({ ...p, pageIndex: 0 }));
        }
      : setSorting,
    onRowSelectionChange: setRowSelection,
    onColumnSizingChange: setColumnSizing,
    onColumnVisibilityChange: setColumnVisibility,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    // We manage page resets explicitly (search enter/clear, view mode,
    // pageSize change) so disable TanStack's auto-reset which would
    // clobber our restored page index when the filter changes.
    autoResetPageIndex: false,
    columnResizeMode,
    enableRowSelection,
    enableColumnResizing,
    ...tableOptions,
  };

  if (isServerSide) {
    tableOpts.manualPagination = true;
    tableOpts.manualSorting = true;
    tableOpts.manualFiltering = true;
    tableOpts.pageCount = serverPageCount;
  } else {
    tableOpts.onGlobalFilterChange = setGlobalFilter;
    tableOpts.getSortedRowModel = getSortedRowModel();
    tableOpts.getPaginationRowModel = getPaginationRowModel();
    tableOpts.getFilteredRowModel = getFilteredRowModel();
    tableOpts.globalFilterFn = (
      row,
      _columnId,
      filterValue: GlobalFilterValue
    ) => {
      // View-mode filter (selected IDs)
      if (
        filterValue.selectedIds != null &&
        !filterValue.selectedIds.has(row.id)
      ) {
        return false;
      }
      // Text search filter
      if (filterValue.searchTerm) {
        const term = filterValue.searchTerm.toLowerCase();
        return row.getAllCells().some((cell) => {
          const value = cell.getValue();
          if (value == null) return false;
          return String(value).toLowerCase().includes(term);
        });
      }
      return true;
    };
  }

  const table = useReactTable(tableOpts);

  // ---- derived values -----------------------------------------------------
  const isAllPageRowsSelected = table.getIsAllPageRowsSelected();
  const isSomePageRowsSelected = table.getIsSomePageRowsSelected();

  const selectionState: OnyxSelectionState = isAllPageRowsSelected
    ? "all"
    : isSomePageRowsSelected
      ? "partial"
      : "none";

  const selectedRowIds = useMemo(
    () => Object.keys(rowSelection),
    [rowSelection]
  );
  const selectedCount = selectedRowIds.length;
  const totalPages = Math.max(1, table.getPageCount());
  const currentPage = pagination.pageIndex + 1;
  const hasActiveFilter =
    !isServerSide &&
    (globalFilter.selectedIds != null || !!globalFilter.searchTerm);
  const totalItems = isServerSide
    ? serverSide!.totalItems
    : hasActiveFilter
      ? table.getPrePaginationRowModel().rows.length
      : data.length;
  const isPaginated = isFinite(pagination.pageSize);

  // ---- selection change callback ------------------------------------------
  const isFirstRenderRef = useRef(true);
  const onSelectionChangeRef = useRef(onSelectionChange);
  onSelectionChangeRef.current = onSelectionChange;

  useEffect(() => {
    if (isFirstRenderRef.current) {
      isFirstRenderRef.current = false;
      return;
    }
    onSelectionChangeRef.current?.(selectedRowIds);
  }, [selectedRowIds]);

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

  const toggleAllRowsSelected = (selected: boolean) => {
    table.toggleAllRowsSelected(selected);
  };

  const isAllRowsSelected = table.getIsAllRowsSelected();

  // ---- view mode (filter to selected rows) --------------------------------
  const isViewingSelected = globalFilter.selectedIds != null;

  const enterViewMode = () => {
    if (isServerSide) return;
    if (selectedRowIds.length > 0) {
      setGlobalFilter((prev) => ({
        ...prev,
        selectedIds: new Set(selectedRowIds),
      }));
      setPagination((prev) => ({ ...prev, pageIndex: 0 }));
    }
  };

  const exitViewMode = () => {
    if (isServerSide) return;
    setGlobalFilter((prev) => ({ ...prev, selectedIds: null }));
    setPagination((prev) => ({ ...prev, pageIndex: 0 }));
  };

  return {
    table,
    currentPage,
    totalPages,
    totalItems,
    pageSize: pagination.pageSize,
    setPage,
    isPaginated,
    selectionState,
    selectedCount,
    selectedRowIds,
    isAllPageRowsSelected,
    isAllRowsSelected,
    clearSelection,
    toggleAllPageRowsSelected,
    toggleAllRowsSelected,
    isViewingSelected,
    enterViewMode,
    exitViewMode,
  };
}
