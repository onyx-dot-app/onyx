"use client";

import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import type { WithoutStyles } from "@/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DraggableProps {
  sortableItems: string[];
  isEnabled: boolean;
}

interface TableBodyProps
  extends WithoutStyles<React.HTMLAttributes<HTMLTableSectionElement>> {
  ref?: React.Ref<HTMLTableSectionElement>;
  /** DnD sortable context — enables drag-and-drop reordering */
  dndSortable?: DraggableProps;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function TableBody({ ref, dndSortable, ...props }: TableBodyProps) {
  if (dndSortable?.isEnabled) {
    const { sortableItems } = dndSortable;
    return (
      <SortableContext
        items={sortableItems}
        strategy={verticalListSortingStrategy}
      >
        <tbody ref={ref} {...props} />
      </SortableContext>
    );
  }

  return <tbody ref={ref} {...props} />;
}

export default TableBody;
export type { TableBodyProps, DraggableProps };
