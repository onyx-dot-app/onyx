import { cn } from "@opal/utils";
import type { WithoutStyles } from "@/types";
import type { ExtremaSizeVariants, SizeVariants } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TableSize = Extract<SizeVariants, "md" | "lg">;
type TableVariant = "rows" | "cards";
type TableQualifier = "simple" | "avatar" | "icon";
type SelectionBehavior = "no-select" | "single-select" | "multi-select";

interface TableProps
  extends WithoutStyles<React.TableHTMLAttributes<HTMLTableElement>> {
  ref?: React.Ref<HTMLTableElement>;
  /** Size preset for the table. @default "lg" */
  size?: TableSize;
  /** Visual row variant. @default "cards" */
  variant?: TableVariant;
  /** Row selection behavior. @default "no-select" */
  selectionBehavior?: SelectionBehavior;
  /** Leading qualifier column type. @default null */
  qualifier?: TableQualifier;
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
  size = "lg",
  variant = "cards",
  selectionBehavior = "no-select",
  qualifier = "simple",
  heightVariant,
  width,
  ...props
}: TableProps) {
  return (
    <table
      ref={ref}
      className={cn("border-separate border-spacing-0", "min-w-full")}
      style={{ tableLayout: "fixed", width: width ?? undefined }}
      data-size={size}
      data-variant={variant}
      data-selection={selectionBehavior}
      data-qualifier={qualifier}
      data-height={heightVariant}
      {...props}
    />
  );
}

export default Table;
export type {
  TableProps,
  TableSize,
  TableVariant,
  TableQualifier,
  SelectionBehavior,
};
