"use client";

import React from "react";
import { cn } from "@opal/utils";
import { useTableSize } from "@opal/components/table/TableSizeContext";
import type { WithoutStyles } from "@/types";
import type { ExtremaSizeVariants, SizeVariants } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TableSize = Extract<SizeVariants, "md" | "lg">;
type TableVariant = "rows" | "cards";
type SelectionBehavior = "no-select" | "single-select" | "multi-select";

interface TableProps
  extends WithoutStyles<React.TableHTMLAttributes<HTMLTableElement>> {
  ref?: React.Ref<HTMLTableElement>;
  /** Visual row variant. @default "cards" */
  variant?: TableVariant;
  /** Row selection behavior. @default "no-select" */
  selectionBehavior?: SelectionBehavior;
  /** Height behavior. `"fit"` = shrink to content, `"full"` = fill available space. */
  heightVariant?: ExtremaSizeVariants;
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
  variant = "cards",
  selectionBehavior = "no-select",
  heightVariant,
  width,
  ...props
}: TableProps) {
  const size = useTableSize();
  return (
    <table
      ref={ref}
      className={cn("border-separate border-spacing-0", !width && "min-w-full")}
      style={{ tableLayout: "fixed", width }}
      data-size={size}
      data-variant={variant}
      data-selection={selectionBehavior}
      data-height={heightVariant}
      {...props}
    />
  );
}

export default Table;
export type { TableProps, TableSize, TableVariant, SelectionBehavior };
