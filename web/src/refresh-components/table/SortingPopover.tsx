"use client";

import { useState } from "react";
import {
  type Table,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { Button } from "@opal/components";
import { SvgSort, SvgCheck } from "@opal/icons";
import Popover from "@/refresh-components/Popover";
import Divider from "@/refresh-components/Divider";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";

// ---------------------------------------------------------------------------
// Popover UI
// ---------------------------------------------------------------------------

interface SortingPopoverProps {
  table: Table<any>;
  sorting: SortingState;
  size?: "regular" | "small";
  footerText?: string;
  ascendingLabel?: string;
  descendingLabel?: string;
}

function SortingPopover({
  table,
  sorting,
  size = "regular",
  footerText,
  ascendingLabel = "Ascending",
  descendingLabel = "Descending",
}: SortingPopoverProps) {
  const [open, setOpen] = useState(false);
  const sortableColumns = table
    .getAllLeafColumns()
    .filter((col) => col.getCanSort());

  const currentSort = sorting[0] ?? null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button
          icon={SvgSort}
          transient={open}
          size={size === "small" ? "sm" : "md"}
          prominence="internal"
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

          <LineItem
            selected={currentSort === null}
            emphasized
            rightChildren={
              currentSort === null ? <SvgCheck size={16} /> : undefined
            }
            onClick={() => {
              table.resetSorting();
            }}
          >
            Manual Ordering
          </LineItem>

          {sortableColumns.map((column) => {
            const isSorted = currentSort?.id === column.id;
            const label =
              typeof column.columnDef.header === "string"
                ? column.columnDef.header
                : column.id;

            return (
              <LineItem
                key={column.id}
                selected={isSorted}
                emphasized
                rightChildren={isSorted ? <SvgCheck size={16} /> : undefined}
                onClick={() => {
                  if (isSorted) return;
                  column.toggleSorting(false);
                }}
              >
                {label}
              </LineItem>
            );
          })}

          <Divider showTitle text="Sorting Order" />

          <LineItem
            selected={currentSort !== null && !currentSort.desc}
            emphasized
            rightChildren={
              currentSort !== null && !currentSort.desc ? (
                <SvgCheck size={16} />
              ) : undefined
            }
            onClick={() => {
              if (currentSort) {
                table.setSorting([{ id: currentSort.id, desc: false }]);
              }
            }}
          >
            {ascendingLabel}
          </LineItem>

          <LineItem
            selected={currentSort !== null && currentSort.desc}
            emphasized
            rightChildren={
              currentSort !== null && currentSort.desc ? (
                <SvgCheck size={16} />
              ) : undefined
            }
            onClick={() => {
              if (currentSort) {
                table.setSorting([{ id: currentSort.id, desc: true }]);
              }
            }}
          >
            {descendingLabel}
          </LineItem>
        </Popover.Menu>
      </Popover.Content>
    </Popover>
  );
}

// ---------------------------------------------------------------------------
// Column definition factory
// ---------------------------------------------------------------------------

interface CreateSortingColumnOptions {
  size?: "regular" | "small";
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
