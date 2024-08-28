import { useSortable } from "@dnd-kit/sortable";
import { TableCell, TableRow } from "@tremor/react";
import { CSS } from "@dnd-kit/utilities";
import { DragHandle } from "./DragHandle";
import { Row } from "./interfaces";

export function DraggableRow({
  row,
  forceDragging,
  isAdmin = true,
}: {
  row: Row;
  forceDragging?: boolean;
  isAdmin?: boolean;
}) {
  const {
    attributes,
    listeners,
    transform,
    transition,
    setNodeRef,
    isDragging,
  } = useSortable({
    id: row.id,
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition: transition,
  };

  return (
    <TableRow
      ref={setNodeRef}
      style={style}
      className={isDragging ? "invisible" : "bg-background"}
    >
      <TableCell>
        {isAdmin && (
          <DragHandle
            isDragging={isDragging || forceDragging}
            {...attributes}
            {...listeners}
          />
        )}
      </TableCell>
      {row.cells.map((column, ind) => (
        <TableCell key={ind}>{column}</TableCell>
      ))}
    </TableRow>
  );
}
