import { cn } from "@opal/utils";
import { useTableSize } from "@opal/components/table/TableSizeContext";
import type { WithoutStyles } from "@/types";

interface TableCellProps
  extends WithoutStyles<React.TdHTMLAttributes<HTMLTableCellElement>> {
  children: React.ReactNode;
  /** Explicit pixel width for the cell. */
  width?: number;
}

export default function TableCell({
  width,
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
        className={cn("tbl-cell-inner", "flex items-center overflow-hidden")}
        data-size={resolvedSize}
      >
        {children}
      </div>
    </td>
  );
}

export type { TableCellProps };
