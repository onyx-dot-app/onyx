import { useState, useMemo, useCallback } from "react";

export interface UseExpandableListOptions<T> {
  items: T[];
  initialCount: number;
  expansionCount: number;
}

export interface UseExpandableListResult<T> {
  /** The currently visible subset of items */
  visibleItems: T[];
  /** Whether there are more items to show */
  hasMore: boolean;
  /** Count of remaining hidden items */
  remainingCount: number;
  /** Expand to show more items */
  showMore: () => void;
  /** Reset to initial count */
  reset: () => void;
}

/**
 * Generic hook for managing "show more" functionality on lists.
 * Tracks how many items to display and provides methods to expand.
 */
export function useExpandableList<T>({
  items,
  initialCount,
  expansionCount,
}: UseExpandableListOptions<T>): UseExpandableListResult<T> {
  const [itemsToShow, setItemsToShow] = useState(initialCount);

  const visibleItems = useMemo(
    () => items.slice(0, itemsToShow),
    [items, itemsToShow]
  );

  const hasMore = items.length > itemsToShow;
  const remainingCount = Math.max(0, items.length - itemsToShow);

  const showMore = useCallback(() => {
    setItemsToShow((prev) => Math.min(prev + expansionCount, items.length));
  }, [expansionCount, items.length]);

  const reset = useCallback(() => {
    setItemsToShow(initialCount);
  }, [initialCount]);

  return {
    visibleItems,
    hasMore,
    remainingCount,
    showMore,
    reset,
  };
}
