import React, { JSX, useState, useEffect, useRef, useMemo } from "react";
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
  const [visibleCount, setVisibleCount] = useState(initialCount);
  const animatedKeysRef = useRef<Set<string>>(new Set());

  const getEntryKey = (entry: DisplayEntry<T>): string => {
    if (entry.type === "more") return `more-button`;
    return String(getKey(entry.item, entry.index));
  };

  const effectiveCount = Math.min(visibleCount, items.length);

  const displayList: DisplayEntry<T>[] = useMemo(() => {
    const chips: DisplayEntry<T>[] = items
      .slice(0, effectiveCount)
      .map((item, i) => ({ type: "chip" as const, item, index: i }));

    if (effectiveCount < items.length) {
      chips.push({ type: "more", batchId: 0 });
    }
    return chips;
  }, [items, effectiveCount]);

  const chipCount = effectiveCount;
  const remainingCount = items.length - chipCount;
  const remainingItems = items.slice(chipCount);

  const handleShowMore = () => {
    setVisibleCount((prev) => prev + expansionCount);
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
