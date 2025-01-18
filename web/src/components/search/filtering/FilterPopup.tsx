import React, { useState } from "react";
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
import { TagFilter } from "./TagFilter";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";

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

interface SelectableItemProps {
  children: React.ReactNode;
  selected: boolean;
  onClick: () => void;
}

const SelectableItem: React.FC<SelectableItemProps> = ({
  children,
  selected,
  onClick,
}) => (
  <div
    className={`px-3 py-2 cursor-pointer transition-colors duration-200 ${
      selected
        ? "bg-accent text-accent-foreground"
        : "hover:bg-accent hover:text-accent-foreground"
    }`}
    onClick={onClick}
  >
    {children}
  </div>
);

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
        <Button variant="outline" size="sm">
          {trigger}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[400px] p-0" align="start">
        <div className="flex h-[325px]">
          <div className="w-1/3 border-r">
            <ScrollArea className="h-full">
              <div className="p-2">
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
            </ScrollArea>
          </div>
          <div className="w-2/3">
            <ScrollArea className="h-full">
              <div className="p-4">
                {selectedFilter === FilterCategories.date && renderCalendar()}
                {selectedFilter === FilterCategories.sources && (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-sm font-semibold">Sources</h3>
                      <Checkbox
                        id="select-all-sources"
                        checked={
                          filterManager.selectedSources.length ===
                          availableSources.length
                        }
                        onCheckedChange={(checked) => {
                          filterManager.setSelectedSources(
                            checked ? availableSources : []
                          );
                        }}
                      />
                    </div>
                    {availableSources.map((source) => (
                      <SelectableItem
                        key={source.internalName}
                        selected={filterManager.selectedSources.some(
                          (s) => s.internalName === source.internalName
                        )}
                        onClick={() => {
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
                      >
                        <div className="flex items-center space-x-2">
                          <SourceIcon
                            sourceType={source.internalName}
                            iconSize={14}
                          />
                          <span className="text-sm">{source.displayName}</span>
                        </div>
                      </SelectableItem>
                    ))}
                  </div>
                )}
                {selectedFilter === FilterCategories.documentSets && (
                  <div>
                    <h3 className="text-sm font-semibold mb-2">
                      Document Sets
                    </h3>
                    <Input
                      placeholder="Search document sets..."
                      value={documentSetSearch}
                      onChange={(e) => setDocumentSetSearch(e.target.value)}
                      className="mb-2"
                    />
                    {availableDocumentSets
                      .filter((docSet) =>
                        docSet.name
                          .toLowerCase()
                          .includes(documentSetSearch.toLowerCase())
                      )
                      .map((docSet) => (
                        <SelectableItem
                          key={docSet.id}
                          selected={filterManager.selectedDocumentSets.includes(
                            docSet.id.toString()
                          )}
                          onClick={() => {
                            filterManager.setSelectedDocumentSets((prev) =>
                              prev.includes(docSet.id.toString())
                                ? prev.filter(
                                    (id) => id !== docSet.id.toString()
                                  )
                                : [...prev, docSet.id.toString()]
                            );
                          }}
                        >
                          <span className="text-sm">{docSet.name}</span>
                        </SelectableItem>
                      ))}
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
            </ScrollArea>
          </div>
        </div>
        <Separator className="my-2" />
        <div className="flex justify-between items-center px-4 py-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              filterManager.clearFilters();
            }}
            className="text-xs"
          >
            Clear Filters
          </Button>
          <div className="text-xs text-muted-foreground flex items-center space-x-1">
            {filterManager.selectedSources.length > 0 && (
              <span className="bg-muted px-1.5 py-0.5 rounded-full">
                {filterManager.selectedSources.length} sources
              </span>
            )}
            {filterManager.selectedDocumentSets.length > 0 && (
              <span className="bg-muted px-1.5 py-0.5 rounded-full">
                {filterManager.selectedDocumentSets.length} sets
              </span>
            )}
            {filterManager.selectedTags.length > 0 && (
              <span className="bg-muted px-1.5 py-0.5 rounded-full">
                {filterManager.selectedTags.length} tags
              </span>
            )}
            {filterManager.timeRange && (
              <span className="bg-muted px-1.5 py-0.5 rounded-full">
                Date range
              </span>
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
