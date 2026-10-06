"use client";

import React from "react";
import { cn } from "@opal/utils";
import { useTableSize } from "@opal/components/table/TableSizeContext";
import type { WithoutStyles } from "@opal/types";
import type { ExtremaSizeVariants, SizeVariants } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TableSize = Extract<SizeVariants, "md" | "lg">;
type SelectionBehavior = "no-select" | "single-select" | "multi-select";

interface TableProps extends WithoutStyles<
  React.TableHTMLAttributes<HTMLTableElement>
> {
  ref?: React.Ref<HTMLTableElement>;
  /** Row selection behavior. @default "no-select" */
  selectionBehavior?: SelectionBehavior;
  /** Height behavior. `"fit"` = shrink to content, `"full"` = fill available space. */
  size?: ExtremaSizeVariants;
  /** Explicit pixel width for the table (e.g. from `table.getTotalSize()`).
   *  When provided the table uses exactly this width instead of stretching
   *  to fill its container, which prevents `table-layout: fixed` from
   *  redistributing extra space across columns on resize. */
  width?: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function Table({
  ref,
  selectionBehavior = "no-select",
  size: heightVariant,
  width,
  ...props
}: TableProps) {
  const size = useTableSize();
  return (
    <table
      ref={ref}
      className={cn("tbl border-separate", !width && "min-w-full")}
      style={{ width }}
      data-size={size}
      data-selection={selectionBehavior}
      data-height={heightVariant}
      {...props}
    />
  );
}

export default Table;
export type { TableProps, TableSize, SelectionBehavior };
