import React from "react";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover"; // shadcn popover
import { FiBook, FiMap, FiTag, FiCalendar } from "react-icons/fi";
import { SourceMetadata } from "@/lib/search/interfaces";
import { Calendar } from "@/components/ui/calendar"; // or wherever your Calendar component lives
import { FilterDropdown } from "@/components/search/filtering/FilterDropdown";
import { listSourceMetadata } from "@/lib/sources";
import { getDateRangeString } from "@/lib/dateUtils";
import { DateRangePickerValue } from "../../dateRangeSelectors/AdminDateRangeSelector";
import { Tag } from "@/lib/types";
import { SourceIcon } from "@/components/SourceIcon";
export interface SourceSelectorProps {
  timeRange: DateRangePickerValue | null;
  setTimeRange: React.Dispatch<
    React.SetStateAction<DateRangePickerValue | null>
  >;
  selectedSources: SourceMetadata[];
  setSelectedSources: React.Dispatch<React.SetStateAction<SourceMetadata[]>>;
  selectedDocumentSets: string[];
  setSelectedDocumentSets: React.Dispatch<React.SetStateAction<string[]>>;
  selectedTags: Tag[];
  setSelectedTags: React.Dispatch<React.SetStateAction<Tag[]>>;
  existingSources: string[]; // e.g. list of internalName that exist
  availableDocumentSets: { name: string }[];
  availableTags: Tag[];
}

export function HorizontalSourceSelector({
  timeRange,
  setTimeRange,
  selectedSources,
  setSelectedSources,
  selectedDocumentSets,
  setSelectedDocumentSets,
  selectedTags,
  setSelectedTags,
  existingSources,
  availableDocumentSets,
  availableTags,
}: SourceSelectorProps) {
  const handleSourceSelect = (source: SourceMetadata) => {
    setSelectedSources((prev: SourceMetadata[]) => {
      if (prev.map((s) => s.internalName).includes(source.internalName)) {
        return prev.filter((s) => s.internalName !== source.internalName);
      } else {
        return [...prev, source];
      }
    });
  };

  const handleDocumentSetSelect = (documentSetName: string) => {
    setSelectedDocumentSets((prev: string[]) => {
      if (prev.includes(documentSetName)) {
        return prev.filter((s) => s !== documentSetName);
      } else {
        return [...prev, documentSetName];
      }
    });
  };

  const handleTagSelect = (tag: Tag) => {
    setSelectedTags((prev: Tag[]) => {
      if (
        prev.some(
          (t) => t.tag_key === tag.tag_key && t.tag_value === tag.tag_value
        )
      ) {
        return prev.filter(
          (t) => !(t.tag_key === tag.tag_key && t.tag_value === tag.tag_value)
        );
      } else {
        return [...prev, tag];
      }
    });
  };

  const resetSources = () => {
    setSelectedSources([]);
  };

  const resetDocuments = () => {
    setSelectedDocumentSets([]);
  };

  const resetTags = () => {
    setSelectedTags([]);
  };

  return (
    <div className="flex flex-row flex-wrap items-center space-x-2">
      {/* Date Range Popover */}
      <Popover>
        <PopoverTrigger asChild>
          <button
            className="
              flex items-center space-x-1 border 
              border-border rounded-lg px-3 py-1.5 
              hover:bg-accent-background-hovered text-sm cursor-pointer
              bg-background-search-filter
            "
          >
            <FiCalendar size={14} />
            <span>
              {timeRange?.from
                ? getDateRangeString(timeRange.from, timeRange.to)
                : "Date Range"}
            </span>
          </button>
        </PopoverTrigger>
        <PopoverContent
          className="bg-background-search-filter border border-border rounded-md z-[200] p-2"
          align="start"
        >
          <Calendar
            mode="range"
            selected={
              timeRange
                ? { from: new Date(timeRange.from), to: new Date(timeRange.to) }
                : undefined
            }
            onSelect={(daterange) => {
              const initialDate = daterange?.from || new Date();
              const endDate = daterange?.to || new Date();
              setTimeRange({
                from: initialDate,
                to: endDate,
                selectValue: timeRange?.selectValue || "",
              });
            }}
            className="rounded-md"
          />
        </PopoverContent>
      </Popover>

      {/* Sources Popover */}
      {existingSources.length > 0 && (
        <FilterDropdown
          icon={<FiMap size={14} />}
          backgroundColor="bg-background-search-filter"
          dropdownColor="bg-background-search-filter-dropdown"
          dropdownWidth="w-40"
          defaultDisplay="Sources"
          resetValues={resetSources}
          width="w-fit"
          options={listSourceMetadata()
            .filter((source) => existingSources.includes(source.internalName))
            .map((source) => ({
              icon: (
                <SourceIcon
                  sourceType={source.baseSourceType || source.internalName}
                  iconSize={14}
                />
              ),
              key: source.internalName,
              display: (
                <span className="flex items-center space-x-2">
                  <span>{source.displayName}</span>
                </span>
              ),
            }))}
          optionClassName="truncate w-full break-all"
          selected={selectedSources.map((src) => src.internalName)}
          handleSelect={(option) => {
            const s = listSourceMetadata().find(
              (m) => m.internalName === option.key
            );
            if (s) handleSourceSelect(s);
          }}
        />
      )}

      {/* Document Sets Popover */}
      {availableDocumentSets.length > 0 && (
        <FilterDropdown
          icon={<FiBook size={14} />}
          backgroundColor="bg-background-search-filter"
          dropdownColor="bg-background-search-filter-dropdown"
          dropdownWidth="w-40"
          defaultDisplay="Sets"
          resetValues={resetDocuments}
          width="w-fit"
          options={availableDocumentSets.map((docSet) => ({
            key: docSet.name,
            display: <>{docSet.name}</>,
          }))}
          optionClassName="truncate w-full break-all"
          selected={selectedDocumentSets}
          handleSelect={(option) => handleDocumentSetSelect(option.key)}
        />
      )}

      {/* Tags Popover */}
      {availableTags.length > 0 && (
        <FilterDropdown
          icon={<FiTag size={14} />}
          backgroundColor="bg-background-search-filter"
          dropdownColor="bg-background-search-filter-dropdown"
          dropdownWidth="w-64"
          defaultDisplay="Tags"
          resetValues={resetTags}
          width="w-fit"
          options={availableTags.map((tag) => ({
            key: `${tag.tag_key}=${tag.tag_value}`,
            display: (
              <span className="text-sm">
                {tag.tag_key}
                <b>=</b>
                {tag.tag_value}
              </span>
            ),
          }))}
          optionClassName="truncate w-full break-all"
          selected={selectedTags.map((t) => `${t.tag_key}=${t.tag_value}`)}
          handleSelect={(option) => {
            const [tKey, tValue] = option.key.split("=");
            const foundTag = availableTags.find(
              (tg) => tg.tag_key === tKey && tg.tag_value === tValue
            );
            if (foundTag) handleTagSelect(foundTag);
          }}
        />
      )}
    </div>
  );
}
