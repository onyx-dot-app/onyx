"use client";

import { useState } from "react";
import {
  type Table,
  type ColumnDef,
  type RowData,
  type VisibilityState,
} from "@tanstack/react-table";
import { Button, Divider, LineItemButton, Tag } from "@opal/components";
import { useTableSize } from "@opal/components/table/TableSizeContext";
import { SvgColumn, SvgCheck } from "@opal/icons";
import { Popover } from "@opal/components/popover/components";
import { useOpalStrings } from "@opal/strings";

// ---------------------------------------------------------------------------
// Popover UI
// ---------------------------------------------------------------------------

interface ColumnVisibilityPopoverProps<TData extends RowData = RowData> {
  table: Table<TData>;
  columnVisibility: VisibilityState;
}

function ColumnVisibilityPopover<TData extends RowData>({
  table,
  columnVisibility,
}: ColumnVisibilityPopoverProps<TData>) {
  const size = useTableSize();
  const strings = useOpalStrings();
  const [open, setOpen] = useState(false);

  // User-defined columns only (exclude internal qualifier/actions)
  const dataColumns = table
    .getAllLeafColumns()
    .filter(
      (col) =>
        !col.id.startsWith("__") &&
        col.id !== "qualifier" &&
        typeof col.columnDef.header === "string" &&
        col.columnDef.header.trim() !== ""
    );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button
          icon={SvgColumn}
          interaction={open ? "hover" : "rest"}
          size={size === "md" ? "sm" : "md"}
          prominence="tertiary"
          tooltip={strings.columns}
        />
      </Popover.Trigger>

      <Popover.Content width="lg" align="end" side="bottom">
        <Divider title={strings.shownColumns} />
        <Popover.Menu>
          {dataColumns.map((column) => {
            const canHide = column.getCanHide();
            const isVisible = columnVisibility[column.id] !== false;
            const label =
              typeof column.columnDef.header === "string"
                ? column.columnDef.header
                : column.id;

            return (
              <LineItemButton
                key={column.id}
                selectVariant="select-heavy"
                state={isVisible ? "selected" : "empty"}
                title={label}
                sizePreset="main-ui"
                rightChildren={
                  !canHide ? (
                    <div className="flex items-center">
                      <Tag title={strings.alwaysShown} color="blue" />
                    </div>
                  ) : isVisible ? (
                    <SvgCheck size={16} className="text-action-selection-05" />
                  ) : undefined
                }
                onClick={canHide ? () => column.toggleVisibility() : undefined}
              />
            );
          })}
        </Popover.Menu>
      </Popover.Content>
    </Popover>
  );
}

// ---------------------------------------------------------------------------
// Column definition factory
// ---------------------------------------------------------------------------

function createColumnVisibilityColumn<TData>(): ColumnDef<TData, unknown> {
  return {
    id: "__columnVisibility",
    size: 44,
    enableHiding: false,
    enableSorting: false,
    enableResizing: false,
    header: ({ table }) => (
      <ColumnVisibilityPopover
        table={table}
        columnVisibility={table.getState().columnVisibility}
      />
    ),
    cell: () => null,
  };
}

export { ColumnVisibilityPopover, createColumnVisibilityColumn };
