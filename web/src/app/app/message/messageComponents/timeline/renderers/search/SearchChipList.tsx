import React, { JSX, useState, useEffect, useRef } from "react";
import { SourceTag, SourceInfo } from "@/refresh-components/buttons/source-tag";
import { cn } from "@/lib/utils";

export type { SourceInfo };

const ANIMATION_DELAY_MS = 30;

export interface SearchChipListProps<T> {
  items: T[];
  initialCount: number;
  expansionCount: number;
  getKey: (item: T, index: number) => string | number;
  toSourceInfo: (item: T, index: number) => SourceInfo;
  onClick?: (item: T) => void;
  emptyState?: React.ReactNode;
  className?: string;
  showDetailsCard?: boolean;
  isQuery?: boolean;
}

type DisplayEntry<T> =
  | { type: "chip"; item: T; index: number }
  | { type: "more"; batchId: number };

export function SearchChipList<T>({
  items,
  initialCount,
  expansionCount,
  getKey,
  toSourceInfo,
  onClick,
  emptyState,
  className = "",
  showDetailsCard,
  isQuery,
}: SearchChipListProps<T>): JSX.Element {
  const [displayList, setDisplayList] = useState<DisplayEntry<T>[]>([]);
  const [batchId, setBatchId] = useState(0);
  const animatedKeysRef = useRef<Set<string>>(new Set());

  const getEntryKey = (entry: DisplayEntry<T>): string => {
    if (entry.type === "more") return `more-button-${entry.batchId}`;
    return String(getKey(entry.item, entry.index));
  };

  useEffect(() => {
    const initial: DisplayEntry<T>[] = items
      .slice(0, initialCount)
      .map((item, i) => ({ type: "chip" as const, item, index: i }));

    if (items.length > initialCount) {
      initial.push({ type: "more", batchId: 0 });
    }

    setDisplayList(initial);
    setBatchId(0);
  }, [items, initialCount]);

  const chipCount = displayList.filter((e) => e.type === "chip").length;
  const remainingCount = items.length - chipCount;
  const remainingItems = items.slice(chipCount);

  const handleShowMore = () => {
    const nextBatchId = batchId + 1;

    setDisplayList((prev) => {
      const withoutButton = prev.filter((e) => e.type !== "more");
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
      if (newCount < items.length) {
        updated.push({ type: "more", batchId: nextBatchId });
      }
      return updated;
    });

    setBatchId(nextBatchId);
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      displayList.forEach((entry) =>
        animatedKeysRef.current.add(getEntryKey(entry))
      );
    }, 0);
    return () => clearTimeout(timer);
  }, [displayList]);

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
              <SourceTag
                displayName={toSourceInfo(entry.item, entry.index).title}
                sources={[toSourceInfo(entry.item, entry.index)]}
                onSourceClick={onClick ? () => onClick(entry.item) : undefined}
                showDetailsCard={showDetailsCard}
                isQuery={isQuery}
                tooltipText={isQuery ? "View Full Search Term" : undefined}
              />
            ) : (
              <SourceTag
                displayName={`+${remainingCount} more`}
                sources={remainingItems.map((item, i) =>
                  toSourceInfo(item, chipCount + i)
                )}
                onSourceClick={() => handleShowMore()}
                showDetailsCard={showDetailsCard}
                isQuery={isQuery}
                isMore={isQuery}
              />
            )}
          </div>
        );
      })}

      {items.length === 0 && emptyState}
    </div>
  );
}
