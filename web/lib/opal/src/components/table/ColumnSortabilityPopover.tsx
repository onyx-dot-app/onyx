"use client";

import { useState } from "react";
import {
  type Table,
  type ColumnDef,
  type RowData,
  type SortingState,
} from "@tanstack/react-table";
import { Button, LineItemButton } from "@opal/components";
import { SvgArrowUpDown, SvgSortOrder, SvgCheck } from "@opal/icons";
import Popover from "@/refresh-components/Popover";
import Divider from "@/refresh-components/Divider";
import Text from "@/refresh-components/texts/Text";

// ---------------------------------------------------------------------------
// Popover UI
// ---------------------------------------------------------------------------

interface SortingPopoverProps<TData extends RowData = RowData> {
  table: Table<TData>;
  sorting: SortingState;
  size?: "md" | "lg";
  footerText?: string;
  ascendingLabel?: string;
  descendingLabel?: string;
}

function SortingPopover<TData extends RowData>({
  table,
  sorting,
  size = "lg",
  footerText,
  ascendingLabel = "Ascending",
  descendingLabel = "Descending",
}: SortingPopoverProps<TData>) {
  const [open, setOpen] = useState(false);
  const sortableColumns = table
    .getAllLeafColumns()
    .filter((col) => col.getCanSort());

  const currentSort = sorting[0] ?? null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button
          icon={currentSort === null ? SvgArrowUpDown : SvgSortOrder}
          interaction={open ? "hover" : "rest"}
          size={size === "md" ? "sm" : "md"}
          prominence="tertiary"
          tooltip="Sort"
        />
      </Popover.Trigger>

      <Popover.Content width="lg" align="end" side="bottom">
        <Popover.Menu
          footer={
            footerText ? (
              <div className="px-2 py-1">
                <Text secondaryBody text03>
                  {footerText}
                </Text>
              </div>
            ) : undefined
          }
        >
          <Divider showTitle text="Sort by" />

          <LineItemButton
            selectVariant="select-heavy"
            state={currentSort === null ? "selected" : "empty"}
            title="Manual Ordering"
            sizePreset="main-ui"
            rightChildren={
              currentSort === null ? (
                <SvgCheck size={16} className="text-action-link-05" />
              ) : undefined
            }
            onClick={() => {
              table.resetSorting();
            }}
          />

          {sortableColumns.map((column) => {
            const isSorted = currentSort?.id === column.id;
            const label =
              typeof column.columnDef.header === "string"
                ? column.columnDef.header
                : column.id;

            return (
              <LineItemButton
                key={column.id}
                selectVariant="select-heavy"
                state={isSorted ? "selected" : "empty"}
                title={label}
                sizePreset="main-ui"
                rightChildren={
                  isSorted ? (
                    <SvgCheck size={16} className="text-action-link-05" />
                  ) : undefined
                }
                onClick={() => {
                  if (isSorted) {
                    table.resetSorting();
                    return;
                  }
                  column.toggleSorting(false);
                }}
              />
            );
          })}

          {currentSort !== null && (
            <>
              <Divider showTitle text="Sorting Order" />

              <LineItemButton
                selectVariant="select-heavy"
                state={!currentSort.desc ? "selected" : "empty"}
                title={ascendingLabel}
                sizePreset="main-ui"
                rightChildren={
                  !currentSort.desc ? (
                    <SvgCheck size={16} className="text-action-link-05" />
                  ) : undefined
                }
                onClick={() => {
                  table.setSorting([{ id: currentSort.id, desc: false }]);
                }}
              />

              <LineItemButton
                selectVariant="select-heavy"
                state={currentSort.desc ? "selected" : "empty"}
                title={descendingLabel}
                sizePreset="main-ui"
                rightChildren={
                  currentSort.desc ? (
                    <SvgCheck size={16} className="text-action-link-05" />
                  ) : undefined
                }
                onClick={() => {
                  table.setSorting([{ id: currentSort.id, desc: true }]);
                }}
              />
            </>
          )}
        </Popover.Menu>
      </Popover.Content>
    </Popover>
  );
}

// ---------------------------------------------------------------------------
// Column definition factory
// ---------------------------------------------------------------------------

interface CreateSortingColumnOptions {
  size?: "md" | "lg";
  footerText?: string;
  ascendingLabel?: string;
  descendingLabel?: string;
}

function createSortingColumn<TData>(
  options?: CreateSortingColumnOptions
): ColumnDef<TData, unknown> {
  return {
    id: "__sorting",
    size: 44,
    enableHiding: false,
    enableSorting: false,
    enableResizing: false,
    header: ({ table }) => (
      <SortingPopover
        table={table}
        sorting={table.getState().sorting}
        size={options?.size}
        footerText={options?.footerText}
        ascendingLabel={options?.ascendingLabel}
        descendingLabel={options?.descendingLabel}
      />
    ),
    cell: () => null,
  };
}

export { SortingPopover, createSortingColumn };
