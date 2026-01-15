import React, { JSX } from "react";
import { SourceChip2 } from "@/app/chat/components/SourceChip2";
import { truncateString } from "@/lib/utils";
import { useExpandableList } from "./useExpandableList";
import { MAX_TITLE_LENGTH } from "./searchStateUtils";

const ANIMATION_DELAY_MS = 30;

export interface SearchChipListProps<T> {
  /** Items to display as chips */
  items: T[];
  /** Number of items to show initially */
  initialCount: number;
  /** Number of items to add when "show more" is clicked */
  expansionCount: number;
  /** Get a unique key for each item */
  getKey: (item: T, index: number) => string | number;
  /** Get the icon element for each item */
  getIcon: (item: T, index: number) => JSX.Element;
  /** Get the title text for each item */
  getTitle: (item: T) => string;
  /** Optional click handler for each chip */
  onClick?: (item: T) => void;
  /** Content to show when the list is empty */
  emptyState?: React.ReactNode;
  /** Additional className for the container */
  className?: string;
}

/**
 * Renders a list of chips with staggered animations and "show more" expansion.
 * Used for displaying search queries and document results.
 */
export function SearchChipList<T>({
  items,
  initialCount,
  expansionCount,
  getKey,
  getIcon,
  getTitle,
  onClick,
  emptyState,
  className = "",
}: SearchChipListProps<T>): JSX.Element {
  const { visibleItems, hasMore, remainingCount, showMore } = useExpandableList(
    {
      items,
      initialCount,
      expansionCount,
    }
  );

  return (
    <div className={`flex flex-wrap gap-x-2 gap-y-2 ml-1 ${className}`}>
      {visibleItems.map((item, index) => (
        <div
          key={getKey(item, index)}
          className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
          style={{
            animationDelay: `${index * ANIMATION_DELAY_MS}ms`,
            animationFillMode: "backwards",
          }}
        >
          <SourceChip2
            icon={getIcon(item, index)}
            title={truncateString(getTitle(item), MAX_TITLE_LENGTH)}
            onClick={onClick ? () => onClick(item) : undefined}
          />
        </div>
      ))}

      {hasMore && (
        <div
          className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
          style={{
            animationDelay: `${visibleItems.length * ANIMATION_DELAY_MS}ms`,
            animationFillMode: "backwards",
          }}
        >
          <SourceChip2 title={`${remainingCount} more...`} onClick={showMore} />
        </div>
      )}

      {items.length === 0 && emptyState}
    </div>
  );
}
