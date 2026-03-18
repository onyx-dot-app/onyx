"use client";

import { useState } from "react";
import {
  type Table,
  type ColumnDef,
  type RowData,
  type VisibilityState,
} from "@tanstack/react-table";
import { Button } from "@opal/components";
import { SvgColumn, SvgCheck } from "@opal/icons";
import Popover from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import Divider from "@/refresh-components/Divider";

// ---------------------------------------------------------------------------
// Popover UI
// ---------------------------------------------------------------------------

interface ColumnVisibilityPopoverProps<TData extends RowData = RowData> {
  table: Table<TData>;
  columnVisibility: VisibilityState;
  size?: "md" | "lg";
}

function ColumnVisibilityPopover<TData extends RowData>({
  table,
  columnVisibility,
  size = "lg",
}: ColumnVisibilityPopoverProps<TData>) {
  const [open, setOpen] = useState(false);
  const hideableColumns = table
    .getAllLeafColumns()
    .filter((col) => col.getCanHide());

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button
          icon={SvgColumn}
          interaction={open ? "hover" : "rest"}
          size={size === "md" ? "sm" : "md"}
          prominence="tertiary"
          tooltip="Columns"
        />
      </Popover.Trigger>

      <Popover.Content width="lg" align="end" side="bottom">
        <Divider showTitle text="Shown Columns" />
        <Popover.Menu>
          {hideableColumns.map((column) => {
            const isVisible = columnVisibility[column.id] !== false;
            const label =
              typeof column.columnDef.header === "string"
                ? column.columnDef.header
                : column.id;

            return (
              <LineItem
                key={column.id}
                selected={isVisible}
                emphasized
                rightChildren={isVisible ? <SvgCheck size={16} /> : undefined}
                onClick={() => {
                  column.toggleVisibility();
                }}
              >
                {label}
              </LineItem>
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

interface CreateColumnVisibilityColumnOptions {
  size?: "md" | "lg";
}

function createColumnVisibilityColumn<TData>(
  options?: CreateColumnVisibilityColumnOptions
): ColumnDef<TData, unknown> {
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
        size={options?.size}
      />
    ),
    cell: () => null,
  };
}

export { ColumnVisibilityPopover, createColumnVisibilityColumn };
