import React, { JSX, useState, useEffect, useRef } from "react";
import { IconProps } from "@/components/icons/icons";
import Tag from "@/refresh-components/buttons/Tag";
import { cn, truncateString } from "@/lib/utils";
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
  /** Get the icon factory for each item */
  getIconFactory: (
    item: T,
    index: number
  ) => React.FunctionComponent<IconProps>;
  /** Get the title text for each item */
  getTitle: (item: T) => string;
  /** Optional click handler for each chip */
  onClick?: (item: T) => void;
  /** Content to show when the list is empty */
  emptyState?: React.ReactNode;
  /** Additional className for the container */
  className?: string;
  /** Optional: get icon factories for "more" button from remaining items */
  getMoreIconFactories?: (
    remainingItems: T[]
  ) => React.FunctionComponent<IconProps>[];
}

type DisplayEntry<T> =
  | { type: "chip"; item: T; index: number }
  | { type: "button"; batchId: number };

/**
 * Renders a list of chips with staggered animations and "show more" expansion.
 * Button is a first-class item in the list, animating naturally with new items.
 */
export function SearchChipList<T>({
  items,
  initialCount,
  expansionCount,
  getKey,
  getIconFactory,
  getTitle,
  onClick,
  emptyState,
  className = "",
  getMoreIconFactories,
}: SearchChipListProps<T>): JSX.Element {
  // List state includes both chips AND the "more" button
  const [displayList, setDisplayList] = useState<DisplayEntry<T>[]>([]);
  const [batchId, setBatchId] = useState(0);

  // Track which keys have already animated
  const animatedKeysRef = useRef<Set<string>>(new Set());

  // Get unique key for each entry
  const getEntryKey = (entry: DisplayEntry<T>): string => {
    if (entry.type === "button") {
      return `more-button-${entry.batchId}`;
    }
    return String(getKey(entry.item, entry.index));
  };

  // Initialize list with initial items + button (if more items exist)
  useEffect(() => {
    const initial: DisplayEntry<T>[] = items
      .slice(0, initialCount)
      .map((item, i) => ({
        type: "chip" as const,
        item,
        index: i,
      }));

    if (items.length > initialCount) {
      initial.push({ type: "button", batchId: 0 });
    }

    setDisplayList(initial);
    setBatchId(0);
    // Don't clear animatedKeysRef - existing items keep their animated state
    // Only new items (not in animatedKeysRef) will animate
  }, [items, initialCount]);

  // Calculate remaining count for button text
  const chipCount = displayList.filter((e) => e.type === "chip").length;
  const remainingCount = items.length - chipCount;

  // Handle "show more" click
  const handleShowMore = () => {
    const nextBatchId = batchId + 1;

    setDisplayList((prev) => {
      // 1. Remove button from list
      const withoutButton = prev.filter((e) => e.type !== "button");

      // 2. Add new items
      const currentCount = withoutButton.length;
      const newCount = Math.min(currentCount + expansionCount, items.length);
      const newItems: DisplayEntry<T>[] = items
        .slice(currentCount, newCount)
        .map((item, i) => ({
          type: "chip" as const,
          item,
          index: currentCount + i,
        }));

      const updated = [...withoutButton, ...newItems];

      // 3. Add button back if more items exist
      if (newCount < items.length) {
        updated.push({ type: "button", batchId: nextBatchId });
      }

      return updated;
    });

    setBatchId(nextBatchId);
  };

  // After render, mark current items as animated (for next render)
  useEffect(() => {
    // Use timeout to mark after this render cycle completes
    const timer = setTimeout(() => {
      displayList.forEach((entry) => {
        animatedKeysRef.current.add(getEntryKey(entry));
      });
    }, 0);
    return () => clearTimeout(timer);
  }, [displayList]);

  // Render with batch-based animation delays
  let newItemCounter = 0;

  return (
    <div className={cn("flex flex-wrap gap-x-2 gap-y-2", className)}>
      {displayList.map((entry) => {
        const key = getEntryKey(entry);
        const isNew = !animatedKeysRef.current.has(key);
        const delay = isNew ? newItemCounter++ * ANIMATION_DELAY_MS : 0;

        return (
          <div
            key={key}
            className={cn("text-xs", {
              "animate-in fade-in slide-in-from-left-2 duration-150": isNew,
            })}
            style={
              isNew
                ? {
                    animationDelay: `${delay}ms`,
                    animationFillMode: "backwards",
                  }
                : undefined
            }
          >
            {entry.type === "chip" ? (
              <Tag
                label={truncateString(getTitle(entry.item), MAX_TITLE_LENGTH)}
                onClick={onClick ? () => onClick(entry.item) : undefined}
              >
                {[getIconFactory(entry.item, entry.index)]}
              </Tag>
            ) : (
              <Tag label={`+${remainingCount} more`} onClick={handleShowMore}>
                {getMoreIconFactories
                  ? getMoreIconFactories(items.slice(chipCount))
                  : [getIconFactory(items[chipCount]!, chipCount)]}
              </Tag>
            )}
          </div>
        );
      })}

      {items.length === 0 && emptyState}
    </div>
  );
}
