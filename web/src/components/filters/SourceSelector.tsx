import React from "react";
import { DocumentSetSummary, Tag, ValidSources } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import { InfoIcon, defaultTailwindCSS } from "@/components/icons/icons";
import { HoverPopup } from "@/components/HoverPopup";
import {
  FiBook,
  FiBookmark,
  FiFilter,
  FiMap,
  FiTag,
  FiX,
} from "react-icons/fi";
import { SearchDateRangeSelector } from "@/components/dateRangeSelectors/SearchDateRangeSelector";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { listSourceMetadata } from "@/lib/sources";
import { SourceIcon } from "@/components/SourceIcon";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { PopoverContent } from "@radix-ui/react-popover";
import { CalendarIcon } from "lucide-react";
import { getTimeAgoString } from "@/lib/dateUtils";
import { FilterDropdown } from "@/components/search/filtering/FilterDropdown";

export interface SourceSelectorProps {
  timeRange: DateRangePickerValue | null;
  setTimeRange: React.Dispatch<
    React.SetStateAction<DateRangePickerValue | null>
  >;
  showDocSidebar?: boolean;
  selectedSources: SourceMetadata[];
  setSelectedSources: React.Dispatch<React.SetStateAction<SourceMetadata[]>>;
  selectedDocumentSets: string[];
  setSelectedDocumentSets: React.Dispatch<React.SetStateAction<string[]>>;
  selectedTags: Tag[];
  setSelectedTags: React.Dispatch<React.SetStateAction<Tag[]>>;
  availableDocumentSets: DocumentSetSummary[];
  existingSources: ValidSources[];
  availableTags: Tag[];
  toggleFilters: () => void;
  filtersUntoggled: boolean;
  tagsOnLeft: boolean;
}

export function SelectedBubble({
  children,
  onClick,
}: {
  children: string | JSX.Element;
  onClick: () => void;
}) {
  return (
    <div
      className={
        "flex cursor-pointer items-center border border-border " +
        "py-1 my-1.5 rounded-lg px-2 w-fit hover:bg-accent-background-hovered"
      }
      onClick={onClick}
    >
      {children}
      <FiX className="ml-2" size={14} />
    </div>
  );
}

export function HorizontalFilters({
  timeRange,
  setTimeRange,
  selectedSources,
  setSelectedSources,
  selectedDocumentSets,
  setSelectedDocumentSets,
  availableDocumentSets,
  existingSources,
}: SourceSelectorProps) {
  const handleSourceSelect = (source: SourceMetadata) => {
    setSelectedSources((prev: SourceMetadata[]) => {
      const prevSourceNames = prev.map((source) => source.internalName);
      if (prevSourceNames.includes(source.internalName)) {
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

  const allSources = listSourceMetadata();
  const availableSources = allSources.filter((source) =>
    existingSources.includes(source.internalName)
  );

  return (
    <div className="b">
      <div className="flex gap-x-3">
        <div className="w-52">
          <SearchDateRangeSelector
            value={timeRange}
            onValueChange={setTimeRange}
          />
        </div>

        <FilterDropdown
          width="w-52"
          options={availableSources.map((source) => {
            return {
              key: source.displayName,
              display: (
                <>
                  <SourceIcon
                    sourceType={source.baseSourceType || source.internalName}
                    iconSize={16}
                  />
                  <span className="ml-2 text-sm">{source.displayName}</span>
                </>
              ),
            };
          })}
          selected={selectedSources.map((source) => source.displayName)}
          handleSelect={(option) =>
            handleSourceSelect(
              allSources.find((source) => source.displayName === option.key)!
            )
          }
          icon={
            <div className="my-auto mr-2 w-[16px] h-[16px]">
              <FiMap size={16} />
            </div>
          }
          defaultDisplay="All Sources"
        />
        {availableDocumentSets.length > 0 && (
          <FilterDropdown
            width="w-52"
            options={availableDocumentSets.map((documentSet) => {
              return {
                key: documentSet.name,
                display: (
                  <>
                    <div className="my-auto">
                      <FiBookmark />
                    </div>
                    <span className="ml-2 text-sm">{documentSet.name}</span>
                  </>
                ),
              };
            })}
            selected={selectedDocumentSets}
            handleSelect={(option) => handleDocumentSetSelect(option.key)}
            icon={
              <div className="my-auto mr-2 w-[16px] h-[16px]">
                <FiBook size={16} />
              </div>
            }
            defaultDisplay="All Document Sets"
          />
        )}
      </div>

      <div className="flex  mt-2">
        <div className="flex flex-wrap gap-x-2">
          {timeRange && timeRange.selectValue && (
            <SelectedBubble onClick={() => setTimeRange(null)}>
              <div className="text-sm flex">{timeRange.selectValue}</div>
            </SelectedBubble>
          )}
          {existingSources.length > 0 &&
            selectedSources.map((source) => (
              <SelectedBubble
                key={source.internalName}
                onClick={() => handleSourceSelect(source)}
              >
                <>
                  <SourceIcon
                    sourceType={source.baseSourceType || source.internalName}
                    iconSize={16}
                  />
                  <span className="ml-2 text-sm">{source.displayName}</span>
                </>
              </SelectedBubble>
            ))}
          {selectedDocumentSets.length > 0 &&
            selectedDocumentSets.map((documentSetName) => (
              <SelectedBubble
                key={documentSetName}
                onClick={() => handleDocumentSetSelect(documentSetName)}
              >
                <>
                  <div>
                    <FiBookmark />
                  </div>
                  <span className="ml-2 text-sm">{documentSetName}</span>
                </>
              </SelectedBubble>
            ))}
        </div>
      </div>
    </div>
  );
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
  availableDocumentSets,
  existingSources,
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
    <div className="flex flex-nowrap  space-x-2">
      <Popover>
        <PopoverTrigger asChild>
          <div
            className={`
              border 
              max-w-36
              border-border 
              rounded-lg 
              max-h-96 
              overflow-y-scroll
              overscroll-contain
              px-3
              text-sm
              py-1.5
              select-none
              cursor-pointer
              w-fit
              gap-x-1
              hover:bg-accent-background-hovered
              flex
              items-center
              bg-background-search-filter
              `}
          >
            <CalendarIcon className="h-4 w-4" />

            {timeRange?.from ? getTimeAgoString(timeRange.from) : "Since"}
          </div>
        </PopoverTrigger>
        <PopoverContent
          className="bg-background-search-filter border-border border rounded-md z-[200] p-0"
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

      {existingSources.length > 0 && (
        <FilterDropdown
          backgroundColor="bg-background-search-filter"
          options={listSourceMetadata()
            .filter((source) => existingSources.includes(source.internalName))
            .map((source) => ({
              key: source.internalName,
              display: (
                <>
                  <SourceIcon
                    sourceType={source.baseSourceType || source.internalName}
                    iconSize={16}
                  />
                  <span className="ml-2 text-sm">{source.displayName}</span>
                </>
              ),
            }))}
          selected={selectedSources.map((source) => source.internalName)}
          handleSelect={(option) =>
            handleSourceSelect(
              listSourceMetadata().find((s) => s.internalName === option.key)!
            )
          }
          icon={<FiMap size={16} />}
          defaultDisplay="Sources"
          dropdownColor="bg-background-search-filter-dropdown"
          width="w-fit ellipsis truncate"
          resetValues={resetSources}
          dropdownWidth="w-40"
          optionClassName="truncate w-full break-all ellipsis"
        />
      )}

      {availableDocumentSets.length > 0 && (
        <FilterDropdown
          backgroundColor="bg-background-search-filter"
          options={availableDocumentSets.map((documentSet) => ({
            key: documentSet.name,
            display: <>{documentSet.name}</>,
          }))}
          selected={selectedDocumentSets}
          handleSelect={(option) => handleDocumentSetSelect(option.key)}
          icon={<FiBook size={16} />}
          defaultDisplay="Sets"
          resetValues={resetDocuments}
          width="w-fit max-w-24 text-ellipsis truncate"
          dropdownColor="bg-background-search-filter-dropdown"
          dropdownWidth="max-w-36 w-fit"
          optionClassName="truncate w-full break-all"
        />
      )}

      {availableTags.length > 0 && (
        <FilterDropdown
          backgroundColor="bg-background-search-filter"
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
          selected={selectedTags.map(
            (tag) => `${tag.tag_key}=${tag.tag_value}`
          )}
          handleSelect={(option) => {
            const [tag_key, tag_value] = option.key.split("=");
            const selectedTag = availableTags.find(
              (tag) => tag.tag_key === tag_key && tag.tag_value === tag_value
            );
            if (selectedTag) {
              handleTagSelect(selectedTag);
            }
          }}
          icon={<FiTag size={16} />}
          defaultDisplay="Tags"
          resetValues={resetTags}
          dropdownColor="bg-background-search-filter-dropdown"
          width="w-fit max-w-24 ellipsis truncate"
          dropdownWidth="max-w-80 w-fit"
          optionClassName="truncate w-full break-all ellipsis"
        />
      )}
    </div>
  );
}
