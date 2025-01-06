import { DocumentSet, Tag, ValidSources } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import { InfoIcon, defaultTailwindCSS } from "@/components/icons/icons";
import { HoverPopup } from "@/components/HoverPopup";
import { DateRangePickerValue } from "@/app/ee/admin/performance/DateRangeSelector";
import { SourceIcon } from "@/components/SourceIcon";
import { Checkbox } from "@/components/ui/checkbox";
import { TagFilter } from "@/components/search/filtering/TagFilter";
import { CardContent } from "@/components/ui/card";
import { useEffect } from "react";
import { useState } from "react";
import { listSourceMetadata } from "@/lib/sources";
import { Calendar } from "@/components/ui/calendar";
import { getDateRangeString } from "@/lib/dateUtils";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ToolTipDetails } from "@/components/admin/connectors/Field";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { TooltipProvider } from "@radix-ui/react-tooltip";

const SectionTitle = ({
  children,
  modal,
}: {
  children: string;
  modal?: boolean;
}) => (
  <div className={`mt-4 pb-2 ${modal ? "w-[80vw]" : "w-full"}`}>
    <p className="text-sm font-semibold">{children}</p>
  </div>
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
  filtersUntoggled: boolean;
  modal?: boolean;
  tagsOnLeft: boolean;
}

export function SourceSelector({
  timeRange,
  filtersUntoggled,
  setTimeRange,
  selectedSources,
  setSelectedSources,
  selectedDocumentSets,
  setSelectedDocumentSets,
  selectedTags,
  setSelectedTags,
  availableDocumentSets,
  existingSources,
  modal,
  availableTags,
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

  let allSourcesSelected = selectedSources.length == existingSources.length;

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

  const [isCalendarOpen, setIsCalendarOpen] = useState(false);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const calendar = document.querySelector(".rdp");
      if (calendar && !calendar.contains(event.target as Node)) {
        setIsCalendarOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  return (
    <div>
      {!filtersUntoggled && (
        <CardContent className=" space-y-2">
          <div>
            <div className="flex py-2 mt-2 justify-start gap-x-2 items-center">
              <p className="text-sm font-semibold">Time Range</p>
              {timeRange && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setTimeRange(null);
                  }}
                  className="text-sm text-gray-500 hover:text-gray-700"
                >
                  Clear
                </button>
              )}
            </div>
            <Popover open={isCalendarOpen} onOpenChange={setIsCalendarOpen}>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  className={`w-full justify-start text-left font-normal`}
                >
                  <span>
                    {getDateRangeString(timeRange?.from!, timeRange?.to!) ||
                      "Select a time range"}
                  </span>
                </Button>
              </PopoverTrigger>
              <PopoverContent className="z-[10000] w-auto p-0" align="start">
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
                    const today = new Date();
                    const initialDate = daterange?.from
                      ? new Date(
                          Math.min(daterange.from.getTime(), today.getTime())
                        )
                      : today;
                    const endDate = daterange?.to
                      ? new Date(
                          Math.min(daterange.to.getTime(), today.getTime())
                        )
                      : today;
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
          </div>

          {availableTags.length > 0 && (
            <div>
              <SectionTitle modal={modal}>Tags</SectionTitle>
              <TagFilter
                modal={modal}
                showTagsOnLeft={true}
                tags={availableTags}
                selectedTags={selectedTags}
                setSelectedTags={setSelectedTags}
              />
            </div>
          )}

          {existingSources.length > 0 && (
            <div>
              <SectionTitle modal={modal}>Sources</SectionTitle>

              <div className="space-y-0">
                {existingSources.length > 1 && (
                  <div className="flex items-center space-x-2 cursor-pointer hover:bg-background-200 rounded-md p-2">
                    <Checkbox
                      id="select-all-sources"
                      checked={allSourcesSelected}
                      onCheckedChange={toggleAllSources}
                    />

                    <label
                      htmlFor="select-all-sources"
                      className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                    >
                      Select All
                    </label>
                  </div>
                )}
                {listSourceMetadata()
                  .filter((source) =>
                    existingSources.includes(source.internalName)
                  )
                  .map((source) => (
                    <div
                      key={source.internalName}
                      className="flex items-center space-x-2 cursor-pointer hover:bg-background-200 rounded-md p-2"
                      onClick={() => handleSelect(source)}
                    >
                      <Checkbox
                        checked={selectedSources
                          .map((s) => s.internalName)
                          .includes(source.internalName)}
                      />
                      <SourceIcon
                        sourceType={source.internalName}
                        iconSize={16}
                      />
                      <span className="text-sm">{source.displayName}</span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {availableDocumentSets.length > 0 && (
            <div>
              <SectionTitle modal={modal}>Knowledge Sets</SectionTitle>
              <div className="space-y-2">
                {availableDocumentSets.map((documentSet) => (
                  <div
                    key={documentSet.name}
                    className="flex items-center space-x-2 cursor-pointer hover:bg-background-200 rounded-md p-2"
                    onClick={() => handleDocumentSetSelect(documentSet.name)}
                  >
                    <Checkbox
                      checked={selectedDocumentSets.includes(documentSet.name)}
                    />
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger>
                          <InfoIcon
                            className={`${defaultTailwindCSS} h-4 w-4`}
                          />
                        </TooltipTrigger>
                        <TooltipContent>
                          <div className="text-sm w-64">
                            <div className="font-medium">Description</div>
                            <div className="mt-1">
                              {documentSet.description}
                            </div>
                          </div>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                    <span className="text-sm">{documentSet.name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      )}
    </div>
  );
}
