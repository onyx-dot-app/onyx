import type { WithoutStyles } from "@opal/types";

interface TableCellProps extends WithoutStyles<
  React.TdHTMLAttributes<HTMLTableCellElement>
> {
  children: React.ReactNode;
  /** Explicit pixel width for the cell. */
  width?: number;
}

export default function TableCell({
  width,
  children,
  ...props
}: TableCellProps) {
  // Size is not declared here — it is read off the parent `.tbl-row[data-size]`
  // via CSS selectors (see styles.css). The cell owns the height; the inner box
  // fills it (`h-full`) and centers its content.
  return (
    <td
      className="tbl-cell overflow-hidden"
      style={width != null ? { width } : undefined}
      {...props}
    >
      <div className="tbl-cell-inner flex h-full items-center overflow-hidden">
        {children}
      </div>
    </td>
  );
}

export type { TableCellProps };
