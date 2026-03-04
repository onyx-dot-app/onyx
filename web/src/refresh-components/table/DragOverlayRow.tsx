import { memo } from "react";
import { type Row, flexRender } from "@tanstack/react-table";
import TableRow from "@/refresh-components/table/TableRow";
import TableCell from "@/refresh-components/table/TableCell";

interface DragOverlayRowProps<TData> {
  row: Row<TData>;
  variant?: "table" | "list";
}

function DragOverlayRowInner<TData>({
  row,
  variant,
}: DragOverlayRowProps<TData>) {
  return (
    <table
      className="min-w-full border-collapse"
      style={{ tableLayout: "fixed" }}
    >
      <tbody>
        <TableRow variant={variant} selected={row.getIsSelected()}>
          {row.getVisibleCells().map((cell) => (
            <TableCell key={cell.id} width={cell.column.getSize()}>
              {flexRender(cell.column.columnDef.cell, cell.getContext())}
            </TableCell>
          ))}
        </TableRow>
      </tbody>
    </table>
  );
}

const DragOverlayRow = memo(DragOverlayRowInner) as typeof DragOverlayRowInner;

export default DragOverlayRow;
export type { DragOverlayRowProps };
