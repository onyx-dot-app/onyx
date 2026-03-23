"use client";
"use no memo";

import "@opal/components/table/styles.css";

import { useEffect, useMemo } from "react";
import { flexRender } from "@tanstack/react-table";
import useDataTable, {
  toOnyxSortDirection,
} from "@opal/components/table/hooks/useDataTable";
import useColumnWidths from "@opal/components/table/hooks/useColumnWidths";
import useDraggableRows from "@opal/components/table/hooks/useDraggableRows";
import TableElement from "@opal/components/table/TableElement";
import TableHeader from "@opal/components/table/TableHeader";
import TableBody from "@opal/components/table/TableBody";
import TableRow from "@opal/components/table/TableRow";
import TableHead from "@opal/components/table/TableHead";
import TableCell from "@opal/components/table/TableCell";
import TableQualifier from "@opal/components/table/TableQualifier";
import QualifierContainer from "@opal/components/table/QualifierContainer";
import ActionsContainer from "@opal/components/table/ActionsContainer";
import DragOverlayRow from "@opal/components/table/DragOverlayRow";
import Footer from "@opal/components/table/Footer";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import { TableSizeProvider } from "@opal/components/table/TableSizeContext";
import { ColumnVisibilityPopover } from "@opal/components/table/ColumnVisibilityPopover";
import { SortingPopover } from "@opal/components/table/ColumnSortabilityPopover";
import type { WidthConfig } from "@opal/components/table/hooks/useColumnWidths";
import type { ColumnDef } from "@tanstack/react-table";
import { cn } from "@opal/utils";
import type {
  DataTableProps as BaseDataTableProps,
  DataTableFooterConfig,
  OnyxColumnDef,
  OnyxDataColumn,
  OnyxQualifierColumn,
  OnyxActionsColumn,
} from "@opal/components/table/types";
import type { TableSize } from "@opal/components/table/TableSizeContext";

// ---------------------------------------------------------------------------
// SelectionBehavior
// ---------------------------------------------------------------------------

type SelectionBehavior = "no-select" | "single-select" | "multi-select";

export type DataTableProps<TData> = BaseDataTableProps<TData> & {
  /** Row selection behavior. @default "no-select" */
  selectionBehavior?: SelectionBehavior;
};

// ---------------------------------------------------------------------------
// Internal: resolve size-dependent widths and build TanStack columns
// ---------------------------------------------------------------------------

interface ProcessedColumns<TData> {
  tanstackColumns: ColumnDef<TData, any>[];
  widthConfig: WidthConfig;
  qualifierColumn: OnyxQualifierColumn<TData> | null;
  /** Map from column ID → OnyxColumnDef for dispatch in render loops. */
  columnKindMap: Map<string, OnyxColumnDef<TData>>;
}

function processColumns<TData>(
  columns: OnyxColumnDef<TData>[],
  size: TableSize
): ProcessedColumns<TData> {
  const tanstackColumns: ColumnDef<TData, any>[] = [];
  const fixedColumnIds = new Set<string>();
  const columnWeights: Record<string, number> = {};
  const columnMinWidths: Record<string, number> = {};
  const columnKindMap = new Map<string, OnyxColumnDef<TData>>();
  let qualifierColumn: OnyxQualifierColumn<TData> | null = null;
  let firstDataColumnSeen = false;

  for (const col of columns) {
    const resolvedWidth =
      typeof col.width === "function" ? col.width(size) : col.width;

    // Clone def to avoid mutating the caller's column definitions
    const clonedDef: ColumnDef<TData, any> = {
      ...col.def,
      id: col.id,
      size:
        "fixed" in resolvedWidth ? resolvedWidth.fixed : resolvedWidth.weight,
    };

    // First data column is never hideable
    if (col.kind === "data" && !firstDataColumnSeen) {
      firstDataColumnSeen = true;
      clonedDef.enableHiding = false;
    }

    tanstackColumns.push(clonedDef);

    const id = col.id;
    columnKindMap.set(id, col);

    if ("fixed" in resolvedWidth) {
      fixedColumnIds.add(id);
    } else {
      columnWeights[id] = resolvedWidth.weight;
      columnMinWidths[id] = resolvedWidth.minWidth ?? 50;
    }

    if (col.kind === "qualifier") qualifierColumn = col;
  }

  return {
    tanstackColumns,
    widthConfig: { fixedColumnIds, columnWeights, columnMinWidths },
    qualifierColumn,
    columnKindMap,
  };
}

// ---------------------------------------------------------------------------
// DataTable component
// ---------------------------------------------------------------------------

/**
 * Config-driven table component that wires together `useDataTable`,
 * `useColumnWidths`, and `useDraggableRows` automatically.
 *
 * Full flexibility via the column definitions from `createTableColumns()`.
 *
 * @example
 * ```tsx
 * const tc = createTableColumns<TeamMember>();
 * const columns = [
 *   tc.qualifier({ content: "icon", getContent: (r) => UserIcon }),
 *   tc.column("name", { header: "Name", weight: 23 }),
 *   tc.column("email", { header: "Email", weight: 28 }),
 *   tc.actions(),
 * ];
 *
 * <Table data={items} columns={columns} footer={{}} />
 * ```
 */
export function Table<TData>(props: DataTableProps<TData>) {
  const {
    data,
    columns,
    getRowId,
    pageSize,
    initialSorting,
    initialColumnVisibility,
    draggable,
    footer,
    size = "lg",
    variant = "cards",
    selectionBehavior = "no-select",
    onSelectionChange,
    onRowClick,
    searchTerm,
    height,
    serverSide,
    emptyState,
  } = props;

  const effectivePageSize = pageSize ?? (footer ? 10 : data.length);

  // Whether the qualifier column should exist in the DOM.
  // Derived from the column definitions: if a qualifier column exists with
  // content !== "simple", always show it. If content === "simple" (or no
  // qualifier column defined), show only for multi-select (checkboxes).
  const qualifierColDef = columns.find(
    (c): c is OnyxQualifierColumn<TData> => c.kind === "qualifier"
  );
  const hasQualifierColumn =
    (qualifierColDef != null && qualifierColDef.content !== "simple") ||
    selectionBehavior === "multi-select";

  // 1. Process columns (memoized on columns + size)
  const { tanstackColumns, widthConfig, qualifierColumn, columnKindMap } =
    useMemo(() => {
      const processed = processColumns(columns, size);
      if (!hasQualifierColumn) {
        // Remove qualifier from TanStack columns and width config entirely
        return {
          ...processed,
          tanstackColumns: processed.tanstackColumns.filter(
            (c) => c.id !== "qualifier"
          ),
          widthConfig: {
            ...processed.widthConfig,
            fixedColumnIds: new Set(
              Array.from(processed.widthConfig.fixedColumnIds).filter(
                (id) => id !== "qualifier"
              )
            ),
          },
          qualifierColumn: null,
        };
      }
      return processed;
    }, [columns, size, hasQualifierColumn]);

  // 2. Call useDataTable
  const {
    table,
    currentPage,
    totalPages,
    totalItems,
    setPage,
    pageSize: resolvedPageSize,
    selectionState,
    selectedCount,
    selectedRowIds,
    clearSelection,
    toggleAllPageRowsSelected,
    toggleAllRowsSelected,
    isAllPageRowsSelected,
    isAllRowsSelected,
    isViewingSelected,
    enterViewMode,
    exitViewMode,
  } = useDataTable({
    data,
    columns: tanstackColumns,
    pageSize: effectivePageSize,
    initialSorting,
    initialColumnVisibility,
    getRowId,
    onSelectionChange,
    searchTerm,
    serverSide: serverSide
      ? {
          totalItems: serverSide.totalItems,
          onSortingChange: serverSide.onSortingChange,
          onPaginationChange: serverSide.onPaginationChange,
          onSearchTermChange: serverSide.onSearchTermChange,
        }
      : undefined,
  });

  // 3. Call useColumnWidths
  const { containerRef, columnWidths, createResizeHandler } = useColumnWidths({
    headers: table.getHeaderGroups()[0]?.headers ?? [],
    ...widthConfig,
  });

  // 4. Call useDraggableRows (conditional — disabled in server-side mode)
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" && serverSide && draggable) {
      console.warn(
        "DataTable: `draggable` is ignored when `serverSide` is enabled. " +
          "Drag-and-drop reordering is not supported with server-side pagination."
      );
    }
  }, [!!serverSide, !!draggable]); // eslint-disable-line react-hooks/exhaustive-deps
  const effectiveDraggable = serverSide ? undefined : draggable;
  const draggableReturn = useDraggableRows({
    data,
    getRowId,
    enabled: !!effectiveDraggable && table.getState().sorting.length === 0,
    onReorder: effectiveDraggable?.onReorder,
  });

  const hasDraggable = !!effectiveDraggable;

  const isSelectable = selectionBehavior !== "no-select";
  const isMultiSelect = selectionBehavior === "multi-select";
  // Checkboxes appear for any selectable table
  const showQualifierCheckbox = isSelectable;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const isServerLoading = !!serverSide?.isLoading;

  function renderFooter(footerConfig: DataTableFooterConfig) {
    // Mode derived from selectionBehavior — single/multi-select use selection
    // footer, no-select uses summary footer.
    if (isSelectable) {
      return (
        <Footer
          mode="selection"
          multiSelect={isMultiSelect}
          selectionState={selectionState}
          selectedCount={selectedCount}
          onClear={
            footerConfig.onClear ??
            (() => {
              if (isViewingSelected) exitViewMode();
              clearSelection();
            })
          }
          onView={
            !serverSide
              ? isViewingSelected
                ? exitViewMode
                : enterViewMode
              : undefined
          }
          isViewingSelected={isViewingSelected}
          pageSize={resolvedPageSize}
          totalItems={totalItems}
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={setPage}
          units={footerConfig.units}
        />
      );
    }

    // Summary mode (no-select only)
    const rangeStart =
      totalItems === 0
        ? 0
        : !isFinite(resolvedPageSize)
          ? 1
          : (currentPage - 1) * resolvedPageSize + 1;
    const rangeEnd = !isFinite(resolvedPageSize)
      ? totalItems
      : Math.min(currentPage * resolvedPageSize, totalItems);

    return (
      <Footer
        mode="summary"
        rangeStart={rangeStart}
        rangeEnd={rangeEnd}
        totalItems={totalItems}
        currentPage={currentPage}
        totalPages={totalPages}
        onPageChange={setPage}
        leftExtra={footerConfig.leftExtra}
        units={footerConfig.units}
      />
    );
  }

  return (
    <TableSizeProvider size={size}>
      <div>
        <div
          className={cn(
            "overflow-x-auto transition-opacity duration-150",
            isServerLoading && "opacity-50 pointer-events-none"
          )}
          ref={containerRef}
          style={{
            ...(height != null
              ? {
                  maxHeight:
                    typeof height === "number" ? `${height}px` : height,
                  overflowY: "auto" as const,
                }
              : undefined),
          }}
        >
          <TableElement
            variant={variant}
            selectionBehavior={selectionBehavior}
            width={
              Object.keys(columnWidths).length > 0
                ? Object.values(columnWidths).reduce((sum, w) => sum + w, 0)
                : undefined
            }
          >
            <colgroup>
              {table.getVisibleLeafColumns().map((col) => (
                <col
                  key={col.id}
                  style={
                    columnWidths[col.id] != null
                      ? { width: columnWidths[col.id] }
                      : undefined
                  }
                />
              ))}
            </colgroup>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header, headerIndex) => {
                    const colDef = columnKindMap.get(header.id);

                    // Qualifier header — select-all checkbox only for multi-select
                    if (colDef?.kind === "qualifier") {
                      return (
                        <QualifierContainer key={header.id} type="head">
                          {isMultiSelect && (
                            <Checkbox
                              checked={isAllRowsSelected}
                              indeterminate={
                                !isAllRowsSelected && selectedCount > 0
                              }
                              onCheckedChange={(checked) => {
                                // Indeterminate → clear all; otherwise toggle normally
                                if (!isAllRowsSelected && selectedCount > 0) {
                                  toggleAllRowsSelected(false);
                                } else {
                                  toggleAllRowsSelected(checked);
                                }
                              }}
                            />
                          )}
                        </QualifierContainer>
                      );
                    }

                    // Actions header
                    if (colDef?.kind === "actions") {
                      const actionsDef = colDef as OnyxActionsColumn<TData>;
                      return (
                        <ActionsContainer key={header.id} type="head">
                          {actionsDef.showColumnVisibility !== false && (
                            <ColumnVisibilityPopover
                              table={table}
                              columnVisibility={
                                table.getState().columnVisibility
                              }
                            />
                          )}
                          {actionsDef.showSorting !== false && (
                            <SortingPopover
                              table={table}
                              sorting={table.getState().sorting}
                              footerText={actionsDef.sortingFooterText}
                            />
                          )}
                        </ActionsContainer>
                      );
                    }

                    // Data / Display header
                    const canSort = header.column.getCanSort();
                    const sortDir = header.column.getIsSorted();
                    const nextHeader = headerGroup.headers[headerIndex + 1];
                    const canResize =
                      header.column.getCanResize() &&
                      !!nextHeader &&
                      !widthConfig.fixedColumnIds.has(nextHeader.id);

                    const dataCol =
                      colDef?.kind === "data"
                        ? (colDef as OnyxDataColumn<TData>)
                        : null;

                    return (
                      <TableHead
                        key={header.id}
                        width={columnWidths[header.id]}
                        sorted={
                          canSort ? toOnyxSortDirection(sortDir) : undefined
                        }
                        onSort={
                          canSort
                            ? () => header.column.toggleSorting()
                            : undefined
                        }
                        icon={dataCol?.icon}
                        resizable={canResize}
                        onResizeStart={
                          canResize
                            ? createResizeHandler(header.id, nextHeader.id)
                            : undefined
                        }
                      >
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                      </TableHead>
                    );
                  })}
                </TableRow>
              ))}
            </TableHeader>

            <TableBody
              dndSortable={hasDraggable ? draggableReturn : undefined}
              renderDragOverlay={
                hasDraggable
                  ? (activeId) => {
                      const row = table
                        .getRowModel()
                        .rows.find((r) => getRowId(r.original) === activeId);
                      if (!row) return null;
                      return (
                        <DragOverlayRow
                          row={row}
                          columnWidths={columnWidths}
                          columnKindMap={columnKindMap}
                          qualifierColumn={qualifierColumn}
                          isSelectable={isSelectable}
                        />
                      );
                    }
                  : undefined
              }
            >
              {emptyState && table.getRowModel().rows.length === 0 && (
                <tr>
                  <td colSpan={table.getVisibleLeafColumns().length}>
                    {emptyState}
                  </td>
                </tr>
              )}
              {table.getRowModel().rows.map((row) => {
                const rowId = hasDraggable ? getRowId(row.original) : undefined;

                return (
                  <TableRow
                    key={row.id}
                    sortableId={rowId}
                    selected={row.getIsSelected()}
                    onClick={() => {
                      if (
                        hasDraggable &&
                        draggableReturn.wasDraggingRef.current
                      ) {
                        return;
                      }
                      if (onRowClick) {
                        onRowClick(row.original);
                      } else if (isSelectable) {
                        if (!isMultiSelect) {
                          // single-select: clear all, then select this row
                          table.toggleAllRowsSelected(false);
                        }
                        row.toggleSelected();
                      }
                    }}
                  >
                    {row.getVisibleCells().map((cell) => {
                      const cellColDef = columnKindMap.get(cell.column.id);

                      // Qualifier cell
                      if (cellColDef?.kind === "qualifier") {
                        const qDef = cellColDef as OnyxQualifierColumn<TData>;

                        return (
                          <QualifierContainer
                            key={cell.id}
                            type="cell"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <TableQualifier
                              content={qDef.content}
                              icon={qDef.getContent?.(row.original)}
                              imageSrc={qDef.getImageSrc?.(row.original)}
                              imageAlt={qDef.getImageAlt?.(row.original)}
                              background={qDef.background}
                              iconSize={qDef.iconSize}
                              selectable={showQualifierCheckbox}
                              selected={
                                showQualifierCheckbox && row.getIsSelected()
                              }
                              onSelectChange={
                                showQualifierCheckbox
                                  ? (checked) => {
                                      if (!isMultiSelect) {
                                        table.toggleAllRowsSelected(false);
                                      }
                                      row.toggleSelected(checked);
                                    }
                                  : undefined
                              }
                            />
                          </QualifierContainer>
                        );
                      }

                      // Actions cell
                      if (cellColDef?.kind === "actions") {
                        return (
                          <ActionsContainer
                            key={cell.id}
                            type="cell"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {flexRender(
                              cell.column.columnDef.cell,
                              cell.getContext()
                            )}
                          </ActionsContainer>
                        );
                      }

                      // Data / Display cell
                      return (
                        <TableCell key={cell.id}>
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                );
              })}
            </TableBody>
          </TableElement>
        </div>

        {footer && renderFooter(footer)}
      </div>
    </TableSizeProvider>
  );
}
