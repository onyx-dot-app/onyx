"use client";
"use no memo";

import "@opal/components/table/styles.css";

import { useEffect, useMemo } from "react";
import { flexRender } from "@tanstack/react-table";
import useDataTable, { toOnyxSortDirection } from "./hooks/useDataTable";
import useColumnWidths from "./hooks/useColumnWidths";
import useDraggableRows from "./hooks/useDraggableRows";
import TableElement from "./TableElement";
import TableHeader from "./TableHeader";
import TableBody from "./TableBody";
import TableRow from "./TableRow";
import TableHead from "./TableHead";
import TableCell from "./TableCell";
import TableQualifier from "./TableQualifier";
import QualifierContainer from "./QualifierContainer";
import ActionsContainer from "./ActionsContainer";
import DragOverlayRow from "./DragOverlayRow";
import Footer from "./Footer";
import { TableSizeProvider } from "./TableSizeContext";
import { ColumnVisibilityPopover } from "./ColumnVisibilityPopover";
import { SortingPopover } from "./SortingPopover";
import type { WidthConfig } from "./hooks/useColumnWidths";
import type { ColumnDef } from "@tanstack/react-table";
import { cn } from "@opal/utils";
import type {
  DataTableProps,
  DataTableFooterConfig,
  OnyxColumnDef,
  OnyxDataColumn,
  OnyxQualifierColumn,
  OnyxActionsColumn,
} from "./types";
import type { TableSize } from "./TableSizeContext";

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
 *   tc.qualifier({ content: "avatar-user", getInitials: (r) => r.initials }),
 *   tc.column("name", { header: "Name", weight: 23, minWidth: 120 }),
 *   tc.column("email", { header: "Email", weight: 28 }),
 *   tc.actions(),
 * ];
 *
 * <DataTable data={items} columns={columns} footer={{ mode: "selection" }} />
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
    onSelectionChange,
    onRowClick,
    searchTerm,
    height,
    headerBackground,
    serverSide,
    emptyState,
  } = props;

  const effectivePageSize = pageSize ?? (footer ? 10 : data.length);

  // 1. Process columns (memoized on columns + size)
  const { tanstackColumns, widthConfig, qualifierColumn, columnKindMap } =
    useMemo(() => processColumns(columns, size), [columns, size]);

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
    isAllPageRowsSelected,
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
  const footerShowView =
    footer?.mode === "selection" ? footer.showView : undefined;
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" && serverSide && footerShowView) {
      console.warn(
        "DataTable: `showView` is ignored when `serverSide` is enabled. " +
          "View mode requires client-side filtering."
      );
    }
  }, [!!serverSide, !!footerShowView]); // eslint-disable-line react-hooks/exhaustive-deps
  const effectiveDraggable = serverSide ? undefined : draggable;
  const draggableReturn = useDraggableRows({
    data,
    getRowId,
    enabled: !!effectiveDraggable && table.getState().sorting.length === 0,
    onReorder: effectiveDraggable?.onReorder,
  });

  const hasDraggable = !!effectiveDraggable;

  const isSelectable =
    qualifierColumn != null && qualifierColumn.selectable !== false;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const isServerLoading = !!serverSide?.isLoading;

  function renderFooter(footerConfig: DataTableFooterConfig) {
    if (footerConfig.mode === "selection") {
      return (
        <Footer
          mode="selection"
          multiSelect={footerConfig.multiSelect !== false}
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
            footerConfig.showView
              ? isViewingSelected
                ? exitViewMode
                : enterViewMode
              : undefined
          }
          pageSize={resolvedPageSize}
          totalItems={totalItems}
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={setPage}
        />
      );
    }

    // Summary mode
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
            ...(headerBackground
              ? ({
                  "--table-header-bg": headerBackground,
                } as React.CSSProperties)
              : undefined),
          }}
        >
          <TableElement
            variant={variant}
            width={
              Object.keys(columnWidths).length > 0
                ? Object.values(columnWidths).reduce((sum, w) => sum + w, 0)
                : undefined
            }
          >
            <colgroup>
              {table.getAllLeafColumns().map((col) => (
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

                    // Qualifier header
                    if (colDef?.kind === "qualifier") {
                      if (qualifierColumn?.header === false) {
                        return (
                          <QualifierContainer key={header.id} type="head" />
                        );
                      }
                      return (
                        <QualifierContainer key={header.id} type="head">
                          <TableQualifier
                            content={
                              qualifierColumn?.headerContentType ?? "simple"
                            }
                            selectable={isSelectable}
                            selected={isSelectable && isAllPageRowsSelected}
                            onSelectChange={
                              isSelectable
                                ? (checked) =>
                                    toggleAllPageRowsSelected(checked)
                                : undefined
                            }
                          />
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
                              size={size}
                            />
                          )}
                          {actionsDef.showSorting !== false && (
                            <SortingPopover
                              table={table}
                              sorting={table.getState().sorting}
                              size={size}
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
                              initials={qDef.getInitials?.(row.original)}
                              icon={qDef.getIcon?.(row.original)}
                              imageSrc={qDef.getImageSrc?.(row.original)}
                              selectable={isSelectable}
                              selected={isSelectable && row.getIsSelected()}
                              onSelectChange={
                                isSelectable
                                  ? (checked) => {
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
