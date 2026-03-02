import { cn } from "@/lib/utils";
import type { WithoutStyles } from "@/types";

interface TableProps
  extends WithoutStyles<React.TableHTMLAttributes<HTMLTableElement>> {
  ref?: React.Ref<HTMLTableElement>;
  /** Explicit pixel width for the table (e.g. from `table.getTotalSize()`).
   *  When provided the table uses exactly this width instead of stretching
   *  to fill its container, which prevents `table-layout: fixed` from
   *  redistributing extra space across columns on resize. */
  width?: number;
}

function Table({ ref, width, ...props }: TableProps) {
  return (
    <table
      ref={ref}
      className={cn(
        "border-separate border-spacing-0",
        width == null && "min-w-full"
      )}
      style={{ tableLayout: "fixed", width: width ?? undefined }}
      {...props}
    />
  );
}

export default Table;
export type { TableProps };
