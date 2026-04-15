"use client";

import { useState, useEffect, type RefObject } from "react";
import { Button } from "@opal/components";
import { Badge } from "@/components/ui/badge";
import { FilterComponent, FilterOptions } from "./FilterComponent";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { BulkCCPairManageMenu } from "./BulkCCPairManageMenu";
import { IndexingStatusRequest } from "@/lib/types";

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
  filterComponentRef: RefObject<{ resetFilters: () => void }>;
  resetPagination: () => void;
  bulkFilters: IndexingStatusRequest;
  bulkActionsEnabled: boolean;
  onBulkActionSuccess: () => void;
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
  bulkFilters,
  bulkActionsEnabled,
  onBulkActionSuccess,
}: SearchAndFilterControlsProps) {
  const [localSearchValue, setLocalSearchValue] = useState(searchQuery);

  useEffect(() => {
    const timer = setTimeout(() => {
      resetPagination();
      onSearchChange(localSearchValue);
    }, 300);

    return () => clearTimeout(timer);
  }, [localSearchValue, onSearchChange, resetPagination]);

  useEffect(() => {
    setLocalSearchValue(searchQuery);
  }, [searchQuery]);

  return (
    <div className="flex items-center justify-between gap-x-3">
      <div className="flex items-center gap-x-2">
        <InputTypeIn
          placeholder="Search Connectors"
          type="text"
          value={localSearchValue}
          onChange={(event) => setLocalSearchValue(event.target.value)}
          className="w-96"
        />

        <Button onClick={hasExpandedSources ? onCollapseAll : onExpandAll}>
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
                className="px-2 py-0.5 text-xs border-red-400 bg-red-100 hover:border-red-600 cursor-pointer hover:bg-red-100 dark:hover:bg-red-900"
                onClick={onClearFilters}
              >
                <span className="text-red-500 dark:text-red-400">Clear</span>
              </Badge>
            </div>
          )}
        </div>
      </div>

      <BulkCCPairManageMenu
        filters={bulkFilters}
        enabled={bulkActionsEnabled}
        onSuccess={onBulkActionSuccess}
      />
    </div>
  );
}