import React, { useState } from "react";
import { DocumentSet, Tag, ValidSources } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import {
  GearIcon,
  InfoIcon,
  MinusIcon,
  PlusCircleIcon,
  PlusIcon,
  defaultTailwindCSS,
} from "../../icons/icons";
import { HoverPopup } from "../../HoverPopup";
import {
  FiBook,
  FiBookmark,
  FiFilter,
  FiMap,
  FiTag,
  FiX,
} from "react-icons/fi";
import { DateRangeSelector } from "../DateRangeSelector";
import { DateRangePickerValue } from "@/app/ee/admin/performance/DateRangeSelector";
import { FilterDropdown } from "./FilterDropdown";
import { listSourceMetadata } from "@/lib/sources";
import { SourceIcon } from "@/components/SourceIcon";
import { TagFilter } from "./TagFilter";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { PopoverContent } from "@radix-ui/react-popover";
import { CalendarIcon } from "lucide-react";
import {
  buildDateString,
  getDateRangeString,
  getTimeAgoString,
} from "@/lib/dateUtils";
import { Separator } from "@/components/ui/separator";

const SectionTitle = ({ children }: { children: string }) => (
  <div className="font-bold text-xs mt-2 flex">{children}</div>
);

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
  availableDocumentSets: DocumentSet[];
  existingSources: ValidSources[];
  availableTags: Tag[];
  toggleFilters?: () => void;
  filtersUntoggled?: boolean;
  tagsOnLeft?: boolean;
}

export function SourceSelector({
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
  showDocSidebar,
  toggleFilters,
  filtersUntoggled,
  tagsOnLeft,
}: SourceSelectorProps) {
  const handleSelect = (source: SourceMetadata) => {
    setSelectedSources((prev: SourceMetadata[]) => {
      if (
        prev.map((source) => source.internalName).includes(source.internalName)
      ) {
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

  let allSourcesSelected = selectedSources.length > 0;

  const toggleAllSources = () => {
    if (allSourcesSelected) {
      setSelectedSources([]);
    } else {
      const allSources = listSourceMetadata().filter((source) =>
        existingSources.includes(source.internalName)
      );
      setSelectedSources(allSources);
    }
  };

  return (
    <div
      className={`hidden ${
        showDocSidebar ? "4xl:block" : "!block"
      } duration-1000 flex ease-out transition-all transform origin-top-right`}
    >
      <button
        onClick={() => toggleFilters && toggleFilters()}
        className="flex text-emphasis"
      >
        <h2 className="font-bold my-auto">Filters</h2>
        <FiFilter className="my-auto ml-2" size="16" />
      </button>
      {!filtersUntoggled && (
        <>
          <Separator />
          <Popover>
            <PopoverTrigger asChild>
              <div className="cursor-pointer">
                <SectionTitle>Time Range</SectionTitle>
                <p className="text-sm text-default mt-2">
                  {getDateRangeString(timeRange?.from!, timeRange?.to!) ||
                    "Select a time range"}
                </p>
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
                    ? {
                        from: new Date(timeRange.from),
                        to: new Date(timeRange.to),
                      }
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
                className="rounded-md "
              />
            </PopoverContent>
          </Popover>

          {availableTags.length > 0 && (
            <>
              <div className="mt-4 mb-2">
                <SectionTitle>Tags</SectionTitle>
              </div>
              <TagFilter
                showTagsOnLeft={true}
                tags={availableTags}
                selectedTags={selectedTags}
                setSelectedTags={setSelectedTags}
              />
            </>
          )}

          {existingSources.length > 0 && (
            <div className="mt-4">
              <div className="flex w-full gap-x-2 items-center">
                <div className="font-bold text-xs mt-2 flex items-center gap-x-2">
                  <p>Sources</p>
                  <input
                    type="checkbox"
                    checked={allSourcesSelected}
                    onChange={toggleAllSources}
                    className="my-auto form-checkbox h-3 w-3 text-primary border-background-900 rounded"
                  />
                </div>
              </div>
              <div className="px-1">
                {listSourceMetadata()
                  .filter((source) =>
                    existingSources.includes(source.internalName)
                  )
                  .map((source) => (
                    <div
                      key={source.internalName}
                      className={
                        "flex cursor-pointer w-full items-center " +
                        "py-1.5 my-1.5 rounded-lg px-2 select-none " +
                        (selectedSources
                          .map((source) => source.internalName)
                          .includes(source.internalName)
                          ? "bg-hover"
                          : "hover:bg-hover-light")
                      }
                      onClick={() => handleSelect(source)}
                    >
                      <SourceIcon
                        sourceType={source.internalName}
                        iconSize={16}
                      />
                      <span className="ml-2 text-sm text-default">
                        {source.displayName}
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {availableDocumentSets.length > 0 && (
            <>
              <div className="mt-4">
                <SectionTitle>Knowledge Sets</SectionTitle>
              </div>
              <div className="px-1">
                {availableDocumentSets.map((documentSet) => (
                  <div key={documentSet.name} className="my-1.5 flex">
                    <div
                      key={documentSet.name}
                      className={
                        "flex cursor-pointer w-full items-center " +
                        "py-1.5 rounded-lg px-2 " +
                        (selectedDocumentSets.includes(documentSet.name)
                          ? "bg-hover"
                          : "hover:bg-hover-light")
                      }
                      onClick={() => handleDocumentSetSelect(documentSet.name)}
                    >
                      <HoverPopup
                        mainContent={
                          <div className="flex my-auto mr-2">
                            <InfoIcon className={defaultTailwindCSS} />
                          </div>
                        }
                        popupContent={
                          <div className="text-sm w-64">
                            <div className="flex font-medium">Description</div>
                            <div className="mt-1">
                              {documentSet.description}
                            </div>
                          </div>
                        }
                        classNameModifications="-ml-2"
                      />
                      <span className="text-sm">{documentSet.name}</span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
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
        "py-1 my-1.5 rounded-lg px-2 w-fit hover:bg-hover"
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
    <div>
      <div className="flex gap-x-3">
        <div className="w-64">
          <DateRangeSelector value={timeRange} onValueChange={setTimeRange} />
        </div>

        <FilterDropdown
          options={availableSources.map((source) => {
            return {
              key: source.displayName,
              display: (
                <>
                  <SourceIcon sourceType={source.internalName} iconSize={16} />
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

        <FilterDropdown
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
      </div>

      <div className="flex pb-4 mt-2 h-12">
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
                  <SourceIcon sourceType={source.internalName} iconSize={16} />
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
              max-w-64
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
              hover:bg-hover
              flex
              items-center
              bg-background-search-filter
              `}
          >
            <CalendarIcon className="h-4 w-4" />

            {timeRange?.from
              ? getDateRangeString(timeRange.from, timeRange.to)
              : "Since"}
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
                  <SourceIcon sourceType={source.internalName} iconSize={16} />
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
