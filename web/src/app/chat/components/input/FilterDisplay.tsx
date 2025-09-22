import React from "react";
import { XIcon } from "lucide-react";

import { FilterPills } from "./FilterPills";
import { SourceMetadata } from "@/lib/search/interfaces";
import { FilterManager } from "@/lib/hooks";
import { Tag } from "@/lib/types";

interface FiltersDisplayProps {
  filterManager: FilterManager;
  toggleFilters: () => void;
}
export default function FiltersDisplay({
  filterManager,
  toggleFilters,
}: FiltersDisplayProps) {
  return (
    <div className="flex my-auto flex-wrap gap-2 px-2">
      {(() => {
        const allFilters = [
          ...filterManager.selectedSources,
          ...filterManager.selectedDocumentSets,
          ...filterManager.selectedTags,
          ...(filterManager.timeRange ? [filterManager.timeRange] : []),
        ];
        const filtersToShow = allFilters.slice(0, 2);
        const remainingFilters = allFilters.length - 2;

        return (
          <>
            {filtersToShow.map((filter, index) => {
              if (typeof filter === "object" && "displayName" in filter) {
                return (
                  <FilterPills<SourceMetadata>
                    key={index}
                    item={filter}
                    itemToString={(source) => source.displayName}
                    onRemove={(source) =>
                      filterManager.setSelectedSources((prev) =>
                        prev.filter(
                          (s) => s.internalName !== source.internalName
                        )
                      )
                    }
                    toggleFilters={toggleFilters}
                  />
                );
              } else if (typeof filter === "string") {
                return (
                  <FilterPills<string>
                    key={index}
                    item={filter}
                    itemToString={(set) => set}
                    onRemove={(set) =>
                      filterManager.setSelectedDocumentSets((prev) =>
                        prev.filter((s) => s !== set)
                      )
                    }
                    toggleFilters={toggleFilters}
                  />
                );
              } else if ("tag_key" in filter) {
                return (
                  <FilterPills<Tag>
                    key={index}
                    item={filter}
                    itemToString={(tag) => `${tag.tag_key}:${tag.tag_value}`}
                    onRemove={(tag) =>
                      filterManager.setSelectedTags((prev) =>
                        prev.filter(
                          (t) =>
                            t.tag_key !== tag.tag_key ||
                            t.tag_value !== tag.tag_value
                        )
                      )
                    }
                    toggleFilters={toggleFilters}
                  />
                );
              } else if ("from" in filter && "to" in filter) {
                return (
                  <div
                    key={index}
                    className="flex items-center bg-background-150 rounded-full px-3 py-1 text-sm"
                  >
                    <span>
                      {filter.from.toLocaleDateString()} -{" "}
                      {filter.to.toLocaleDateString()}
                    </span>
                    <XIcon
                      onClick={() => filterManager.setTimeRange(null)}
                      size={16}
                      className="ml-2 text-text-400 hover:text-text-600 cursor-pointer"
                    />
                  </div>
                );
              }
            })}
            {remainingFilters > 0 && (
              <div className="flex items-center bg-background-150 rounded-full px-3 py-1 text-sm">
                <span>+{remainingFilters} more</span>
              </div>
            )}
          </>
        );
      })()}
    </div>
  );
}
