import { cn } from "@opal/utils";
import { useTableSize } from "@opal/components/table/TableSizeContext";
import type { WithoutStyles } from "@opal/types";

interface TableCellProps extends WithoutStyles<
  React.TdHTMLAttributes<HTMLTableCellElement>
> {
  children: React.ReactNode;
  /** Explicit pixel width for the cell. */
  width?: number;
  alignment?: "left" | "center" | "right";
  /** Content never widens the column; long content is cut off instead. */
  truncate?: boolean;
}

const alignmentJustifyClass = {
  left: "justify-start",
  center: "justify-center",
  right: "justify-end",
} as const;

export default function TableCell({
  width,
  alignment = "left",
  truncate = false,
  children,
  ...props
}: TableCellProps) {
  const resolvedSize = useTableSize();
  return (
    <td
      className="tbl-cell overflow-hidden"
      data-size={resolvedSize}
      style={width != null ? { width } : undefined}
      {...props}
    >
      <div
        className={cn(
          "tbl-cell-inner",
          "flex items-center overflow-hidden",
          // w-0 + min-w-full: content does not widen the column under
          // `table-layout: auto`.
          truncate && "w-0 min-w-full",
          alignmentJustifyClass[alignment]
        )}
        data-size={resolvedSize}
      >
        {children}
      </div>
    </td>
  );
}

export type { TableCellProps };
