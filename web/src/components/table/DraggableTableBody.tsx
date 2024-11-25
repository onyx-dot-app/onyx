import React, { useMemo, useState } from "react";
import {
  closestCenter,
  DndContext,
  DragEndEvent,
  DragOverlay,
  DragStartEvent,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  UniqueIdentifier,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { restrictToVerticalAxis } from "@dnd-kit/modifiers";
import {
  arrayMove,
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { TableBody } from "@/components/ui/table";
import { DraggableRow } from "./DraggableRow";
import { Row } from "./interfaces";

export function DraggableTableBody({
  rows,
  setRows,
}: {
  rows: Row[];
  setRows: React.Dispatch<React.SetStateAction<UniqueIdentifier[]>>;
}) {
  const [activeId, setActiveId] = useState<UniqueIdentifier | null>();
  const items = useMemo(() => rows?.map(({ id }) => id), [rows]);
  const sensors = useSensors(
    useSensor(MouseSensor, {}),
    useSensor(TouchSensor, {}),
    useSensor(KeyboardSensor, {})
  );

  function handleDragStart(event: DragStartEvent) {
    setActiveId(event.active.id);
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (over !== null && active.id !== over.id) {
      setRows((oldRows) => {
        const oldIndex = items.indexOf(active.id);
        const newIndex = items.indexOf(over.id);
        return arrayMove(oldRows, oldIndex, newIndex);
      });
    }

    setActiveId(null);
  }

  function handleDragCancel() {
    setActiveId(null);
  }

  const selectedRow = useMemo(() => {
    if (activeId === null || activeId === undefined) {
      return null;
    }
    const row = rows.find(({ id }) => id === activeId);
    return row;
  }, [activeId, rows]);

  // Render the UI for your table
  return (
    <DndContext
      sensors={sensors}
      onDragEnd={handleDragEnd}
      onDragStart={handleDragStart}
      onDragCancel={handleDragCancel}
      collisionDetection={closestCenter}
      modifiers={[restrictToVerticalAxis]}
    >
      <TableBody>
        <SortableContext items={items} strategy={verticalListSortingStrategy}>
          {rows.map((row) => {
            return <DraggableRow key={row.id} row={row} />;
          })}
        </SortableContext>
        <DragOverlay>
          {selectedRow && (
            <DraggableRow key={selectedRow.id} row={selectedRow} />
          )}
        </DragOverlay>
      </TableBody>
    </DndContext>
  );
}
