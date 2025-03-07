import { useSortable } from "@dnd-kit/sortable";
import { TableCell, TableRow } from "@/components/ui/table";
import { CSS } from "@dnd-kit/utilities";
import { DragHandle } from "./DragHandle";
import { Row } from "./interfaces";

export function DraggableRow({
  row,
  isAdmin = true,
  isDragOverlay = false,
}: {
  row: Row;
  isAdmin?: boolean;
  isDragOverlay?: boolean;
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
    disabled: isDragOverlay,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <TableRow
      ref={setNodeRef}
      style={isDragOverlay ? undefined : style}
      className={isDragging && !isDragOverlay ? "opacity-0" : ""}
    >
      <TableCell>
        {isAdmin && <DragHandle isDragging={isDragging} {...listeners} />}
      </TableCell>
      {row.cells.map((cell, index) => (
        <TableCell key={index}>{cell}</TableCell>
      ))}
    </TableRow>
  );
}
