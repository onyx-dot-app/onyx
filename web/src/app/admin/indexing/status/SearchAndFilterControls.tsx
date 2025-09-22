"use client";

import { useState, useEffect } from "react";
import { FiX } from "react-icons/fi";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FilterComponent, FilterOptions } from "./FilterComponent";

interface SearchAndFilterControlsProps {
  searchQuery: string;
  onSearchChange: (query: string) => void;
  hasExpandedSources: boolean;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  filterOptions: FilterOptions;
  onFilterChange: (filterOptions: FilterOptions) => void;
  onClearFilters: () => void;
  hasActiveFilters: boolean;
  filterComponentRef: React.RefObject<{ resetFilters: () => void }>;
  resetPagination: () => void;
}

export function SearchAndFilterControls({
  searchQuery,
  onSearchChange,
  hasExpandedSources,
  onExpandAll,
  onCollapseAll,
  filterOptions,
  onFilterChange,
  onClearFilters,
  hasActiveFilters,
  filterComponentRef,
  resetPagination,
}: SearchAndFilterControlsProps) {
  const [localSearchValue, setLocalSearchValue] = useState(searchQuery);

  // Debounce the search query
  useEffect(() => {
    const timer = setTimeout(() => {
      resetPagination();
      onSearchChange(localSearchValue);
    }, 300);

    return () => clearTimeout(timer);
  }, [localSearchValue, onSearchChange, resetPagination]);

  // Sync with external searchQuery changes (e.g., when filters are cleared)
  useEffect(() => {
    setLocalSearchValue(searchQuery);
  }, [searchQuery]);

  const handleClearSearch = () => {
    setLocalSearchValue("");
  };

  return (
    <div className="flex items-center gap-x-2 -mb-4">
      <div className="relative w-96 flex-none">
        <input
          type="text"
          placeholder="Search connectors..."
          value={localSearchValue}
          onChange={(e) => setLocalSearchValue(e.target.value)}
          className="w-full h-9 border border-border rounded-md bg-background-50 px-3 py-1 pr-9 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
        {localSearchValue && (
          <button
            onClick={handleClearSearch}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition-colors"
            aria-label="Clear search"
          >
            <FiX className="h-4 w-4 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" />
          </button>
        )}
      </div>

      <Button
        className="h-9"
        onClick={hasExpandedSources ? onCollapseAll : onExpandAll}
      >
        {hasExpandedSources ? "Collapse All" : "Expand All"}
      </Button>

      <div className="flex items-center gap-2">
        <FilterComponent
          onFilterChange={onFilterChange}
          ref={filterComponentRef}
        />

        {hasActiveFilters && (
          <div className="flex flex-none items-center gap-1 ml-2 max-w-[500px]">
            {filterOptions.accessType &&
              filterOptions.accessType.length > 0 && (
                <Badge variant="secondary" className="px-2 py-0.5 text-xs">
                  Access: {filterOptions.accessType.join(", ")}
                </Badge>
              )}

            {filterOptions.lastStatus &&
              filterOptions.lastStatus.length > 0 && (
                <Badge variant="secondary" className="px-2 py-0.5 text-xs">
                  Status:{" "}
                  {filterOptions.lastStatus
                    .map((s) => s.replace(/_/g, " "))
                    .join(", ")}
                </Badge>
              )}

            {filterOptions.docsCountFilter.operator &&
              filterOptions.docsCountFilter.value !== null && (
                <Badge variant="secondary" className="px-2 py-0.5 text-xs">
                  Docs {filterOptions.docsCountFilter.operator}{" "}
                  {filterOptions.docsCountFilter.value}
                </Badge>
              )}

            {filterOptions.docsCountFilter.operator &&
              filterOptions.docsCountFilter.value === null && (
                <Badge variant="secondary" className="px-2 py-0.5 text-xs">
                  Docs {filterOptions.docsCountFilter.operator} any
                </Badge>
              )}

            <Badge
              variant="outline"
              className="px-2 py-0.5 text-xs border-red-400  bg-red-100 hover:border-red-600 cursor-pointer hover:bg-red-100 dark:hover:bg-red-900"
              onClick={onClearFilters}
            >
              <span className="text-red-500 dark:text-red-400">Clear</span>
            </Badge>
          </div>
        )}
      </div>
    </div>
  );
}
