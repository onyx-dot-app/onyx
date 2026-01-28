import React from "react";
import { XIcon } from "lucide-react";
import { SourceMetadata } from "@/lib/search/interfaces";
import { Tag } from "@/lib/types";

type FilterItem = SourceMetadata | string | Tag;

interface FilterPillsProps<T extends FilterItem> {
  item: T;
  itemToString: (item: T) => string;
  onRemove: (item: T) => void;
  toggleFilters?: () => void;
}

export function FilterPills<T extends FilterItem>({
  item,
  itemToString,
  onRemove,
  toggleFilters,
}: FilterPillsProps<T>) {
  return (
    <button
      onClick={toggleFilters}
      className="cursor-pointer flex flex-wrap gap-2"
    >
      <div className="flex items-center bg-background-150 rounded-full px-3 py-1 text-sm">
        <span>{itemToString(item)}</span>
        <XIcon
          onClick={(e) => {
            e.stopPropagation();
            onRemove(item);
          }}
          size={16}
          className="ml-2 text-text-400 hover:text-text-600 cursor-pointer"
        />
      </div>
    </button>
  );
}
