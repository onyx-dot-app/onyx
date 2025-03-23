import React from "react";
import { FiFilter, FiChevronDown } from "react-icons/fi";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { SourceMetadata } from "@/lib/search/interfaces";
import { SourceIcon } from "@/components/SourceIcon";
import { FilterIcon, SearchIcon } from "lucide-react";
import { FilterManager } from "@/lib/hooks";
import { DocumentSet, Tag } from "@/lib/types";
import { MoreFiltersPopup } from "./MoreFiltersPopup";

interface SearchFiltersProps {
  totalResults: number;
  selectedSources: string[];
  setSelectedSources: (sources: string[]) => void;
  availableSources: SourceMetadata[];
  sourceResults: Record<string, number>;
  filterManager: FilterManager;
  availableDocumentSets: DocumentSet[];
  availableTags: Tag[];
}

export function SearchFilters({
  totalResults,
  selectedSources,
  setSelectedSources,
  availableSources,
  sourceResults,
  filterManager,
  availableDocumentSets,
  availableTags,
}: SearchFiltersProps) {
  // Toggle source selection
  const toggleSource = (source: string) => {
    if (source === "all") {
      // If "All" is clicked, either select only "all" or clear if already selected
      setSelectedSources(selectedSources.includes("all") ? [] : ["all"]);
    } else {
      // If any other source is clicked
      const newSelectedSources = [...selectedSources].filter(
        (s) => s !== "all"
      );

      // Toggle the clicked source
      if (newSelectedSources.includes(source)) {
        newSelectedSources.splice(newSelectedSources.indexOf(source), 1);
      } else {
        newSelectedSources.push(source);
      }

      // If no sources are selected, default to "all"
      setSelectedSources(
        newSelectedSources.length > 0 ? newSelectedSources : ["all"]
      );
    }
  };

  return (
    <div className="flex flex-col w-full">
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm text-gray-500">Found {totalResults} results</p>
        <div className="flex items-center gap-1 text-gray-500">
          <FilterIcon size={14} />
        </div>
      </div>

      <div className="flex flex-col w-full space-y-1">
        <FilterButton
          label="All"
          icon={<SearchIcon size={16} className="text-gray-500" />}
          count={totalResults}
          isSelected={selectedSources.includes("all")}
          onClick={() => toggleSource("all")}
        />

        {availableSources.map((source) => (
          <FilterButton
            key={source.internalName}
            label={source.displayName}
            count={sourceResults[source.internalName] || 0}
            isSelected={selectedSources.includes(source.internalName)}
            onClick={() => toggleSource(source.internalName)}
            icon={<SourceIcon sourceType={source.internalName} iconSize={16} />}
          />
        ))}

        <MoreFiltersPopup
          filterManager={filterManager}
          availableSources={availableSources}
          availableDocumentSets={availableDocumentSets}
          availableTags={availableTags}
          trigger={
            <div
              className={`flex items-center justify-between px-3 py-2 rounded-md cursor-pointer hover:bg-gray-100`}
            >
              <div className="flex items-center gap-2">
                <FilterIcon size={16} />
                <span className="text-sm">More Filters</span>
              </div>
              <div className="flex items-center space-x-1">
                {(filterManager.selectedSources.length > 0 ||
                  filterManager.selectedDocumentSets.length > 0 ||
                  filterManager.selectedTags.length > 0 ||
                  filterManager.timeRange) && (
                  <span className="bg-blue-100 text-blue-800 text-xs px-1.5 py-0.5 rounded-full">
                    Active
                  </span>
                )}
              </div>
            </div>
          }
        />
      </div>
    </div>
  );
}

interface FilterButtonProps {
  label: string;
  count: number;
  isSelected: boolean;
  onClick: () => void;
  icon?: React.ReactNode;
}

function FilterButton({
  label,
  count,
  isSelected,
  onClick,
  icon,
}: FilterButtonProps) {
  return (
    <div
      className={`flex items-center justify-between px-3 py-2 rounded-md cursor-pointer ${
        isSelected
          ? "bg-blue-50 text-blue-700 font-medium"
          : "hover:bg-gray-100"
      }`}
      onClick={onClick}
    >
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-sm">{label}</span>
      </div>
      <span className="text-sm text-gray-500">{count}</span>
    </div>
  );
}
