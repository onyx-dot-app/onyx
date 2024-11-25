import { TableCell, TableRow } from "@/components/ui/table";
import { DragHandle } from "./DragHandle";
import { Row } from "./interfaces";

export function StaticRow({ row }: { row: Row }) {
  return (
    <TableRow className="bg-background border-b border-border">
      <TableCell>
        <DragHandle isDragging />
      </TableCell>
      {row.cells.map((column, ind) => {
        const rowModifier =
          row.staticModifiers &&
          row.staticModifiers.find((mod) => mod[0] === ind);
        return (
          <TableCell key={ind} className={rowModifier && rowModifier[1]}>
            {column}
          </TableCell>
        );
      })}
    </TableRow>
  );
}
