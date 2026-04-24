"use client";

import type { ReactNode } from "react";
import {
  DndContext,
  DragOverlay,
  type DragStartEvent,
  type DragEndEvent,
  type CollisionDetection,
  type Modifier,
  type SensorDescriptor,
  type SensorOptions,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import type { WithoutStyles } from "@/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DraggableProps {
  dndContextProps: {
    sensors: SensorDescriptor<SensorOptions>[];
    collisionDetection: CollisionDetection;
    modifiers: Modifier[];
    onDragStart: (event: DragStartEvent) => void;
    onDragEnd: (event: DragEndEvent) => void;
    onDragCancel: () => void;
  };
  sortableItems: string[];
  activeId: string | null;
  isEnabled: boolean;
}

interface TableBodyProps
  extends WithoutStyles<React.HTMLAttributes<HTMLTableSectionElement>> {
  ref?: React.Ref<HTMLTableSectionElement>;
  /** DnD context props from useDraggableRows — enables drag-and-drop reordering */
  dndSortable?: DraggableProps;
  /** Render function for the drag overlay row */
  renderDragOverlay?: (activeId: string) => ReactNode;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function TableBody({
  ref,
  dndSortable,
  renderDragOverlay,
  ...props
}: TableBodyProps) {
  if (dndSortable?.isEnabled) {
    const { dndContextProps, sortableItems, activeId } = dndSortable;
    return (
      <DndContext
        sensors={dndContextProps.sensors}
        collisionDetection={dndContextProps.collisionDetection}
        modifiers={dndContextProps.modifiers}
        onDragStart={dndContextProps.onDragStart}
        onDragEnd={dndContextProps.onDragEnd}
        onDragCancel={dndContextProps.onDragCancel}
      >
        <SortableContext
          items={sortableItems}
          strategy={verticalListSortingStrategy}
        >
          <tbody ref={ref} {...props} />
        </SortableContext>
        <DragOverlay dropAnimation={null}>
          {activeId && renderDragOverlay ? renderDragOverlay(activeId) : null}
        </DragOverlay>
      </DndContext>
    );
  }

  return <tbody ref={ref} {...props} />;
}

export default TableBody;
export type { TableBodyProps, DraggableProps };
