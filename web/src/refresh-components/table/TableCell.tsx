import { cn } from "@/lib/utils";
import { useTableSize } from "@/refresh-components/table/TableSizeContext";
import type { TableSize } from "@/refresh-components/table/TableSizeContext";
import type { WithoutStyles } from "@/types";

interface TableCellProps
  extends WithoutStyles<React.TdHTMLAttributes<HTMLTableCellElement>> {
  children: React.ReactNode;
  size?: TableSize;
  /** Explicit pixel width for the cell. */
  width?: number;
}

export default function TableCell({
  size,
  width,
  children,
  ...props
}: TableCellProps) {
  const contextSize = useTableSize();
  const resolvedSize = size ?? contextSize;
  return (
    <td
      className="tbl-cell overflow-hidden"
      data-size={resolvedSize}
      style={width != null ? { width } : undefined}
      {...props}
    >
      <div
        className={cn("tbl-cell-inner", "flex items-center overflow-hidden")}
        data-size={resolvedSize}
      >
        {children}
      </div>
    </td>
  );
}

export type { TableCellProps };
