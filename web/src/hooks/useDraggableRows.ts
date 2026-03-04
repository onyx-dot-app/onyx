"use client";

import { useState, useCallback, useMemo } from "react";
import {
  useSensors,
  useSensor,
  PointerSensor,
  KeyboardSensor,
  closestCenter,
  type DragStartEvent,
  type DragEndEvent,
} from "@dnd-kit/core";
import { arrayMove, sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import { restrictToVerticalAxis } from "@dnd-kit/modifiers";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface UseDraggableRowsOptions<TData> {
  /** Current display-order data. */
  data: TData[];
  /** Extract a unique string ID from each row. */
  getRowId: (row: TData) => string;
  /** Disable DnD (e.g. when column sorting is active). @default true */
  enabled?: boolean;
  /** Called after a successful reorder with the new ID order and a map of changed positions. */
  onReorder?: (
    ids: string[],
    changedOrders: Record<string, number>
  ) => void | Promise<void>;
}

interface DraggableRowsReturn {
  /** Props to pass to TableBody's `dndSortable` prop. */
  dndContextProps: {
    sensors: ReturnType<typeof useSensors>;
    collisionDetection: typeof closestCenter;
    modifiers: Array<typeof restrictToVerticalAxis>;
    onDragStart: (event: DragStartEvent) => void;
    onDragEnd: (event: DragEndEvent) => void;
    onDragCancel: () => void;
  };
  /** Ordered list of IDs for SortableContext. */
  sortableItems: string[];
  /** ID of the currently dragged row, or null. */
  activeId: string | null;
  /** Whether a drag is in progress. */
  isDragging: boolean;
  /** Whether DnD is enabled. */
  isEnabled: boolean;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export default function useDraggableRows<TData>(
  options: UseDraggableRowsOptions<TData>
): DraggableRowsReturn {
  const { data, getRowId, enabled = true, onReorder } = options;

  const [activeId, setActiveId] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 5 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const sortableItems = useMemo(
    () => data.map((row) => getRowId(row)),
    [data, getRowId]
  );

  const sortableIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    for (let i = 0; i < sortableItems.length; i++) {
      const item = sortableItems[i];
      if (item !== undefined) {
        map.set(item, i);
      }
    }
    return map;
  }, [sortableItems]);

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveId(String(event.active.id));
  }, []);

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveId(null);
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const oldIndex = sortableIndexMap.get(String(active.id));
      const newIndex = sortableIndexMap.get(String(over.id));
      if (oldIndex === undefined || newIndex === undefined) return;

      const reordered = arrayMove(sortableItems, oldIndex, newIndex);

      const minIdx = Math.min(oldIndex, newIndex);
      const maxIdx = Math.max(oldIndex, newIndex);
      const changedOrders: Record<string, number> = {};
      for (let i = minIdx; i <= maxIdx; i++) {
        const id = reordered[i];
        if (id !== undefined) {
          changedOrders[id] = i;
        }
      }

      onReorder?.(reordered, changedOrders);
    },
    [sortableItems, sortableIndexMap, onReorder]
  );

  const handleDragCancel = useCallback(() => {
    setActiveId(null);
  }, []);

  return {
    dndContextProps: {
      sensors,
      collisionDetection: closestCenter,
      modifiers: [restrictToVerticalAxis],
      onDragStart: handleDragStart,
      onDragEnd: handleDragEnd,
      onDragCancel: handleDragCancel,
    },
    sortableItems,
    activeId,
    isDragging: activeId !== null,
    isEnabled: enabled,
  };
}
