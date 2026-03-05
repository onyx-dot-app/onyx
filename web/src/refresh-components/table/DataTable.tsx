"use client";
"use no memo";

import { useMemo } from "react";
import { flexRender } from "@tanstack/react-table";
import useDataTable, {
  toOnyxSortDirection,
} from "@/refresh-components/table/hooks/useDataTable";
import useColumnWidths from "@/refresh-components/table/hooks/useColumnWidths";
import useDraggableRows from "@/refresh-components/table/hooks/useDraggableRows";
import Table from "@/refresh-components/table/Table";
import TableHeader from "@/refresh-components/table/TableHeader";
import TableBody from "@/refresh-components/table/TableBody";
import TableRow from "@/refresh-components/table/TableRow";
import TableHead from "@/refresh-components/table/TableHead";
import TableCell from "@/refresh-components/table/TableCell";
import TableQualifier from "@/refresh-components/table/TableQualifier";
import QualifierContainer from "@/refresh-components/table/QualifierContainer";
import ActionsContainer from "@/refresh-components/table/ActionsContainer";
import DragOverlayRow from "@/refresh-components/table/DragOverlayRow";
import Footer from "@/refresh-components/table/Footer";
import { TableSizeProvider } from "@/refresh-components/table/TableSizeContext";
import { ColumnVisibilityPopover } from "@/refresh-components/table/ColumnVisibilityPopover";
import { SortingPopover } from "@/refresh-components/table/SortingPopover";
import type { WidthConfig } from "@/refresh-components/table/hooks/useColumnWidths";
import type { ColumnDef } from "@tanstack/react-table";
import type {
  DataTableProps,
  DataTableFooterConfig,
  OnyxColumnDef,
  OnyxDataColumn,
  OnyxQualifierColumn,
  OnyxActionsColumn,
} from "@/refresh-components/table/types";
import type { TableSize } from "@/refresh-components/table/TableSizeContext";

const noopGetRowId = () => "";

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
export default function DataTable<TData>(props: DataTableProps<TData>) {
  const {
    data,
    columns,
    pageSize,
    initialSorting,
    initialColumnVisibility,
    draggable,
    footer,
    size = "regular",
    onRowClick,
    height,
    headerBackground,
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
    clearSelection,
    toggleAllPageRowsSelected,
    isAllPageRowsSelected,
  } = useDataTable({
    data,
    columns: tanstackColumns,
    pageSize: effectivePageSize,
    initialSorting,
    initialColumnVisibility,
  });

  // 3. Call useColumnWidths
  const { containerRef, columnWidths, createResizeHandler } = useColumnWidths({
    headers: table.getHeaderGroups()[0]?.headers ?? [],
    ...widthConfig,
  });

  // 4. Call useDraggableRows (conditional)
  const draggableReturn = useDraggableRows({
    data,
    getRowId: draggable?.getRowId ?? noopGetRowId,
    enabled: !!draggable && table.getState().sorting.length === 0,
    onReorder: draggable?.onReorder,
  });

  const hasDraggable = !!draggable;
  const rowVariant = hasDraggable ? "table" : "list";

  const isSelectable =
    qualifierColumn != null && qualifierColumn.selectable !== false;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  function renderContent() {
    return (
      <div>
        <div
          className="overflow-x-auto"
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
          <Table>
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
                        .rows.find(
                          (r) => draggable!.getRowId(r.original) === activeId
                        );
                      if (!row) return null;
                      return <DragOverlayRow row={row} variant={rowVariant} />;
                    }
                  : undefined
              }
            >
              {table.getRowModel().rows.map((row) => {
                const rowId = hasDraggable
                  ? draggable!.getRowId(row.original)
                  : undefined;

                return (
                  <TableRow
                    key={row.id}
                    variant={rowVariant}
                    sortableId={rowId}
                    selected={row.getIsSelected()}
                    onClick={() => {
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
                          <ActionsContainer key={cell.id} type="cell">
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
          </Table>
        </div>

        {footer && renderFooter(footer)}
      </div>
    );
  }

  function renderFooter(footerConfig: DataTableFooterConfig) {
    if (footerConfig.mode === "selection") {
      return (
        <Footer
          mode="selection"
          multiSelect={footerConfig.multiSelect !== false}
          selectionState={selectionState}
          selectedCount={selectedCount}
          onClear={footerConfig.onClear ?? clearSelection}
          onView={footerConfig.onView}
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
      />
    );
  }

  return <TableSizeProvider size={size}>{renderContent()}</TableSizeProvider>;
}
