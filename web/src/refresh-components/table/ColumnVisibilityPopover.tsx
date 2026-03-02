"use client";

import {
  type Table,
  type ColumnDef,
  type VisibilityState,
} from "@tanstack/react-table";
import { Button } from "@opal/components";
import { SvgColumn, SvgCheck } from "@opal/icons";
import Popover from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";

// ---------------------------------------------------------------------------
// Popover UI
// ---------------------------------------------------------------------------

interface ColumnVisibilityPopoverProps {
  table: Table<any>;
  columnVisibility: VisibilityState;
  size?: "regular" | "small";
}

function ColumnVisibilityPopover({
  table,
  columnVisibility,
  size = "regular",
}: ColumnVisibilityPopoverProps) {
  const hideableColumns = table
    .getAllLeafColumns()
    .filter((col) => col.getCanHide());

  return (
    <Popover>
      <Popover.Trigger asChild>
        <Button
          icon={SvgColumn}
          size={size === "small" ? "sm" : "md"}
          prominence="internal"
          tooltip="Columns"
        />
      </Popover.Trigger>

      <Popover.Content width="lg" align="end" side="bottom">
        <div className="px-2 pt-1.5 pb-1">
          <Text secondaryBody text03>
            Shown Columns
          </Text>
        </div>
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
  size?: "regular" | "small";
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
