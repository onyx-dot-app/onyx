import React, { useState, useEffect } from "react";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import {
  FiCalendar,
  FiTag,
  FiChevronLeft,
  FiChevronRight,
  FiDatabase,
  FiBook,
} from "react-icons/fi";
import { FilterManager } from "@/lib/hooks";
import { DocumentSet, Tag } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import { Checkbox } from "@/components/ui/checkbox";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { SourceIcon } from "@/components/SourceIcon";
import { SelectableDropdown, TagFilter } from "./TagFilter";
import { Input } from "@/components/ui/input";

interface FilterPopupProps {
  filterManager: FilterManager;
  trigger: React.ReactNode;
  availableSources: SourceMetadata[];
  availableDocumentSets: DocumentSet[];
  availableTags: Tag[];
}

export enum FilterCategories {
  date = "date",
  sources = "sources",
  documentSets = "documentSets",
  tags = "tags",
}

export function FilterPopup({
  availableSources,
  availableDocumentSets,
  availableTags,
  filterManager,
  trigger,
}: FilterPopupProps) {
  const [selectedFilter, setSelectedFilter] = useState<FilterCategories>(
    FilterCategories.date
  );
  const [currentDate, setCurrentDate] = useState(new Date());
  const [documentSetSearch, setDocumentSetSearch] = useState("");
  const [filteredDocumentSets, setFilteredDocumentSets] = useState<
    DocumentSet[]
  >(availableDocumentSets);

  useEffect(() => {
    const lowercasedFilter = documentSetSearch.toLowerCase();
    const filtered = availableDocumentSets.filter((docSet) =>
      docSet.name.toLowerCase().includes(lowercasedFilter)
    );
    setFilteredDocumentSets(filtered);
  }, [documentSetSearch, availableDocumentSets]);

  const FilterOption = ({
    category,
    icon,
    label,
  }: {
    category: FilterCategories;
    icon: React.ReactNode;
    label: string;
  }) => (
    <li
      className={`px-3 py-2 flex items-center gap-x-2 cursor-pointer transition-colors duration-200 ${
        selectedFilter === category
          ? "bg-background-100 text-text-900"
          : "text-text-600 hover:bg-background-50"
      }`}
      onMouseDown={() => {
        setSelectedFilter(category);
      }}
    >
      {icon}
      <span className="text-sm font-medium">{label}</span>
    </li>
  );

  const renderCalendar = () => {
    const daysInMonth = new Date(
      currentDate.getFullYear(),
      currentDate.getMonth() + 1,
      0
    ).getDate();
    const firstDayOfMonth = new Date(
      currentDate.getFullYear(),
      currentDate.getMonth(),
      1
    ).getDay();
    const days = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

    const isDateInRange = (date: Date) => {
      if (!filterManager.timeRange) return false;
      return (
        date >= filterManager.timeRange.from &&
        date <= filterManager.timeRange.to
      );
    };

    const isStartDate = (date: Date) =>
      filterManager.timeRange?.from.toDateString() === date.toDateString();
    const isEndDate = (date: Date) =>
      filterManager.timeRange?.to.toDateString() === date.toDateString();

    return (
      <div className="w-full">
        <div className="flex justify-between items-center mb-4">
          <button
            onClick={() =>
              setCurrentDate(
                new Date(
                  currentDate.getFullYear(),
                  currentDate.getMonth() - 1,
                  1
                )
              )
            }
            className="text-text-600 hover:text-text-800"
          >
            <FiChevronLeft size={20} />
          </button>
          <span className="text-base font-semibold">
            {currentDate.toLocaleString("default", {
              month: "long",
              year: "numeric",
            })}
          </span>
          <button
            onClick={() =>
              setCurrentDate(
                new Date(
                  currentDate.getFullYear(),
                  currentDate.getMonth() + 1,
                  1
                )
              )
            }
            className="text-text-600 hover:text-text-800"
          >
            <FiChevronRight size={20} />
          </button>
        </div>
        <div className="grid grid-cols-7 gap-1 text-center mb-2">
          {days.map((day) => (
            <div key={day} className="text-xs font-medium text-text-400">
              {day}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-1 text-center">
          {Array.from({ length: firstDayOfMonth }).map((_, index) => (
            <div key={`empty-${index}`} />
          ))}
          {Array.from({ length: daysInMonth }).map((_, index) => {
            const date = new Date(
              currentDate.getFullYear(),
              currentDate.getMonth(),
              index + 1
            );
            const isInRange = isDateInRange(date);
            const isStart = isStartDate(date);
            const isEnd = isEndDate(date);
            return (
              <button
                key={index + 1}
                className={`w-8 h-8 text-sm rounded-full flex items-center justify-center
                  ${isInRange ? "bg-blue-100" : "hover:bg-background-100"}
                  ${isStart || isEnd ? "bg-blue-500 text-white" : ""}
                  ${
                    isInRange && !isStart && !isEnd
                      ? "text-blue-600"
                      : "text-text-700"
                  }
                `}
                onClick={() => {
                  if (!filterManager.timeRange || (isStart && isEnd)) {
                    filterManager.setTimeRange({
                      from: date,
                      to: date,
                      selectValue: "",
                    });
                  } else if (date < filterManager.timeRange.from) {
                    filterManager.setTimeRange({
                      ...filterManager.timeRange,
                      from: date,
                    });
                  } else {
                    filterManager.setTimeRange({
                      ...filterManager.timeRange,
                      to: date,
                    });
                  }
                }}
              >
                {index + 1}
              </button>
            );
          })}
        </div>
      </div>
    );
  };

  const toggleAllSources = () => {
    if (filterManager.selectedSources.length === availableSources.length) {
      filterManager.setSelectedSources([]);
    } else {
      filterManager.setSelectedSources([...availableSources]);
    }
  };

  const isSourceSelected = (source: SourceMetadata) =>
    filterManager.selectedSources.some(
      (s) => s.internalName === source.internalName
    );

  const toggleSource = (source: SourceMetadata) => {
    if (isSourceSelected(source)) {
      filterManager.setSelectedSources(
        filterManager.selectedSources.filter(
          (s) => s.internalName !== source.internalName
        )
      );
    } else {
      filterManager.setSelectedSources([
        ...filterManager.selectedSources,
        source,
      ]);
    }
  };

  const isDocumentSetSelected = (docSet: DocumentSet) =>
    filterManager.selectedDocumentSets.includes(docSet.name);

  const toggleDocumentSet = (docSet: DocumentSet) => {
    filterManager.setSelectedDocumentSets((prev) =>
      prev.includes(docSet.name)
        ? prev.filter((id) => id !== docSet.name)
        : [...prev, docSet.name]
    );
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button>{trigger}</button>
      </PopoverTrigger>
      <PopoverContent
        className="bg-background w-[400px] p-0 shadow-lg"
        align="start"
      >
        <div className="flex h-[325px]">
          <div className="w-1/3 border-r border-background-200 p-2">
            <ul className="space-y-1">
              <FilterOption
                category={FilterCategories.date}
                icon={<FiCalendar className="w-4 h-4" />}
                label="Date"
              />
              {availableSources.length > 0 && (
                <FilterOption
                  category={FilterCategories.sources}
                  icon={<FiDatabase className="w-4 h-4" />}
                  label="Sources"
                />
              )}
              {availableDocumentSets.length > 0 && (
                <FilterOption
                  category={FilterCategories.documentSets}
                  icon={<FiBook className="w-4 h-4" />}
                  label="Sets"
                />
              )}
              {availableTags.length > 0 && (
                <FilterOption
                  category={FilterCategories.tags}
                  icon={<FiTag className="w-4 h-4" />}
                  label="Tags"
                />
              )}
            </ul>
          </div>
          <div className="w-2/3 overflow-y-auto">
            {selectedFilter === FilterCategories.date && (
              <div className="p-4">
                {renderCalendar()}
                {filterManager.timeRange ? (
                  <div className="mt-2 text-xs text-text-600">
                    Selected:{" "}
                    {filterManager.timeRange.from.toLocaleDateString()} -{" "}
                    {filterManager.timeRange.to.toLocaleDateString()}
                  </div>
                ) : (
                  <div className="mt-2 text-xs text-text-600">
                    No time restriction selected
                  </div>
                )}

                {filterManager.timeRange && (
                  <button
                    onClick={() => {
                      filterManager.setTimeRange(null);
                    }}
                    className="mt-2 text-xs text-text-dark hover:text-text transition-colors duration-200"
                  >
                    Reset Date Filter
                  </button>
                )}
              </div>
            )}
            {selectedFilter === FilterCategories.sources && (
              <div className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-semibold">Sources</h3>
                  <div className="flex gap-x-2 items-center ">
                    <p className="text-xs text-text-dark">Select all</p>
                    <Checkbox
                      size="sm"
                      id="select-all-sources"
                      checked={
                        filterManager.selectedSources.length ===
                        availableSources.length
                      }
                      onCheckedChange={toggleAllSources}
                    />
                  </div>
                </div>
                <ul className="space-y-1 default-scrollbar overflow-y-auto max-h-64">
                  {availableSources.map((source) => (
                    <SelectableDropdown
                      icon={
                        <SourceIcon
                          sourceType={source.internalName}
                          iconSize={14}
                        />
                      }
                      key={source.internalName}
                      value={source.displayName}
                      selected={isSourceSelected(source)}
                      toggle={() => toggleSource(source)}
                    />
                  ))}
                </ul>
              </div>
            )}
            {selectedFilter === FilterCategories.documentSets && (
              <div className="pt-4 h-full flex flex-col w-full">
                <div className="flex pb-2 px-4">
                  <Input
                    placeholder="Search document sets..."
                    value={documentSetSearch}
                    onChange={(e) => setDocumentSetSearch(e.target.value)}
                    className="border border-text-subtle w-full"
                  />
                </div>
                <div className="space-y-1 border-t pt-2 border-t-text-subtle px-4 default-scrollbar w-full max-h-64 overflow-y-auto">
                  {filteredDocumentSets.map((docSet) => (
                    <SelectableDropdown
                      key={docSet.id}
                      value={docSet.name}
                      selected={isDocumentSetSelected(docSet)}
                      toggle={() => toggleDocumentSet(docSet)}
                    />
                  ))}
                </div>
              </div>
            )}
            {selectedFilter === FilterCategories.tags && (
              <TagFilter
                tags={availableTags}
                selectedTags={filterManager.selectedTags}
                setSelectedTags={filterManager.setSelectedTags}
              />
            )}
          </div>
        </div>
        <Separator className="mt-0 mb-2" />
        <div className="flex justify-between items-center px-4 py-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              filterManager.setTimeRange(null);
              filterManager.setSelectedSources([]);
              filterManager.setSelectedDocumentSets([]);
              filterManager.setSelectedTags([]);
            }}
            className="text-xs"
          >
            Clear Filters
          </Button>
          <div className="text-xs text-text-500 flex items-center space-x-1">
            {filterManager.selectedSources.length > 0 && (
              <span className="bg-background-100 dark:bg-neutral-800 px-1.5 py-0.5 rounded-full">
                {filterManager.selectedSources.length} sources
              </span>
            )}
            {filterManager.selectedDocumentSets.length > 0 && (
              <span className="bg-background-100 dark:bg-neutral-800 px-1.5 py-0.5 rounded-full">
                {filterManager.selectedDocumentSets.length} sets
              </span>
            )}
            {filterManager.selectedTags.length > 0 && (
              <span className="bg-background-100 dark:bg-neutral-800 px-1.5 py-0.5 rounded-full">
                {filterManager.selectedTags.length} tags
              </span>
            )}
            {filterManager.timeRange && (
              <span className="bg-background-100 dark:bg-neutral-800 px-1.5 py-0.5 rounded-full">
                Date range
              </span>
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
