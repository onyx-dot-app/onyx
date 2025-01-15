import React, { useState } from "react";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import {
  FiCalendar,
  FiFilter,
  FiFolder,
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
          ? "bg-gray-100 text-gray-900"
          : "text-gray-600 hover:bg-gray-50"
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
            className="text-gray-600 hover:text-gray-800"
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
            className="text-gray-600 hover:text-gray-800"
          >
            <FiChevronRight size={20} />
          </button>
        </div>
        <div className="grid grid-cols-7 gap-1 text-center mb-2">
          {days.map((day) => (
            <div key={day} className="text-xs font-medium text-gray-400">
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
                  ${isInRange ? "bg-blue-100" : "hover:bg-gray-100"}
                  ${isStart || isEnd ? "bg-blue-500 text-white" : ""}
                  ${
                    isInRange && !isStart && !isEnd
                      ? "text-blue-600"
                      : "text-gray-700"
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
          <div className="w-1/3 border-r border-gray-200 p-2">
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
          <div className="w-2/3 p-4 overflow-y-auto">
            {selectedFilter === FilterCategories.date && (
              <div>
                {renderCalendar()}
                {filterManager.timeRange ? (
                  <div className="mt-2 text-xs text-gray-600">
                    Selected:{" "}
                    {filterManager.timeRange.from.toLocaleDateString()} -{" "}
                    {filterManager.timeRange.to.toLocaleDateString()}
                  </div>
                ) : (
                  <div className="mt-2 text-xs text-gray-600">
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
              <div>
                <h3 className="text-sm font-semibold mb-2">Sources</h3>
                <ul className="space-y-2">
                  {availableSources.map((source) => (
                    <li
                      key={source.internalName}
                      className="flex items-center space-x-2"
                    >
                      <Checkbox
                        id={source.internalName}
                        checked={filterManager.selectedSources.some(
                          (s) => s.internalName === source.internalName
                        )}
                        onCheckedChange={() => {
                          filterManager.setSelectedSources((prev) =>
                            prev.some(
                              (s) => s.internalName === source.internalName
                            )
                              ? prev.filter(
                                  (s) => s.internalName !== source.internalName
                                )
                              : [...prev, source]
                          );
                        }}
                      />
                      <div className="flex items-center space-x-1">
                        <SourceIcon
                          sourceType={source.internalName}
                          iconSize={14}
                        />
                        <label
                          htmlFor={source.internalName}
                          className="text-sm cursor-pointer"
                        >
                          {source.displayName}
                        </label>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {selectedFilter === FilterCategories.documentSets && (
              <div>
                <h3 className="text-sm font-semibold mb-2">Document Sets</h3>
                <ul className="space-y-2">
                  {availableDocumentSets.map((docSet) => (
                    <li key={docSet.id} className="flex items-center space-x-2">
                      <Checkbox
                        id={docSet.id.toString()}
                        checked={filterManager.selectedDocumentSets.includes(
                          docSet.id.toString()
                        )}
                        onCheckedChange={() => {
                          filterManager.setSelectedDocumentSets((prev) =>
                            prev.includes(docSet.id.toString())
                              ? prev.filter((id) => id !== docSet.id.toString())
                              : [...prev, docSet.id.toString()]
                          );
                        }}
                      />
                      <label
                        htmlFor={docSet.id.toString()}
                        className="text-sm cursor-pointer"
                      >
                        {docSet.name}
                      </label>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {selectedFilter === FilterCategories.tags && (
              <div>
                <h3 className="text-sm font-semibold mb-2">Tags</h3>
                <ul className="space-y-2">
                  {availableTags.map((tag) => (
                    <li
                      key={tag.tag_value}
                      className="flex items-center space-x-2"
                    >
                      <Checkbox
                        id={tag.tag_value}
                        checked={filterManager.selectedTags.some(
                          (t) => t.tag_value === tag.tag_value
                        )}
                        onCheckedChange={() => {
                          filterManager.setSelectedTags((prev) =>
                            prev.some((t) => t.tag_value === tag.tag_value)
                              ? prev.filter(
                                  (t) => t.tag_value !== tag.tag_value
                                )
                              : [...prev, tag]
                          );
                        }}
                      />
                      <label
                        htmlFor={tag.tag_value}
                        className="text-sm cursor-pointer"
                      >
                        {tag.tag_value}
                      </label>
                    </li>
                  ))}
                </ul>
              </div>
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
          <div className="text-xs text-gray-500 flex items-center space-x-1">
            {filterManager.selectedSources.length > 0 && (
              <span className="bg-gray-100 px-1.5 py-0.5 rounded-full">
                {filterManager.selectedSources.length} sources
              </span>
            )}
            {filterManager.selectedDocumentSets.length > 0 && (
              <span className="bg-gray-100 px-1.5 py-0.5 rounded-full">
                {filterManager.selectedDocumentSets.length} sets
              </span>
            )}
            {filterManager.selectedTags.length > 0 && (
              <span className="bg-gray-100 px-1.5 py-0.5 rounded-full">
                {filterManager.selectedTags.length} tags
              </span>
            )}
            {filterManager.timeRange && (
              <span className="bg-gray-100 px-1.5 py-0.5 rounded-full">
                Date range
              </span>
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
