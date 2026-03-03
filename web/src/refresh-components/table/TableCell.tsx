import { cn } from "@/lib/utils";
import { useTableSize } from "@/refresh-components/table/TableSizeContext";
import type { TableSize } from "@/refresh-components/table/TableSizeContext";
import type { WithoutStyles } from "@/types";

interface TableCellProps
  extends WithoutStyles<React.TdHTMLAttributes<HTMLTableCellElement>> {
  children: React.ReactNode;
  size?: TableSize;
  /** When `true`, pins the cell to the right edge of the scroll container. */
  sticky?: boolean;
  /** Explicit pixel width for the cell. */
  width?: number;
}

export default function TableCell({
  size,
  sticky,
  width,
  children,
  ...props
}: TableCellProps) {
  const contextSize = useTableSize();
  const resolvedSize = size ?? contextSize;
  return (
    <td
      className="tbl-cell"
      data-size={resolvedSize}
      data-sticky={sticky || undefined}
      style={width != null ? { width } : undefined}
      {...props}
    >
      <div
        className={cn("tbl-cell-inner", "flex items-center")}
        data-size={resolvedSize}
      >
        {children}
      </div>
    </td>
  );
}

export type { TableCellProps };
