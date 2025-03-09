import React from "react";
import { FiFilter, FiChevronDown } from "react-icons/fi";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { SourceMetadata } from "@/lib/search/interfaces";
import { SourceIcon } from "@/components/SourceIcon";
import { FilterIcon, SearchIcon } from "lucide-react";

interface SearchFiltersProps {
  totalResults: number;
  selectedFilter: string;
  setSelectedFilter: (filter: string) => void;
  availableSources: SourceMetadata[];
  sourceResults: Record<string, number>;
}

export function SearchFilters({
  totalResults,
  selectedFilter,
  setSelectedFilter,
  availableSources,
  sourceResults,
}: SearchFiltersProps) {
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
          isSelected={selectedFilter === "all"}
          onClick={() => setSelectedFilter("all")}
        />

        {availableSources.map((source) => (
          <FilterButton
            key={source.internalName}
            label={source.displayName}
            count={sourceResults[source.internalName] || 0}
            isSelected={selectedFilter === source.internalName}
            onClick={() => setSelectedFilter(source.internalName)}
            icon={<SourceIcon sourceType={source.internalName} iconSize={16} />}
          />
        ))}
        <MoreFilters
          label="More Filters"
          count={0}
          isSelected={false}
          onClick={() => {}}
          icon={<FilterIcon size={16} />}
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
function MoreFilters({
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
