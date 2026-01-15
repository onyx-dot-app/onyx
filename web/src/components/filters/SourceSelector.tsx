import React, { JSX } from "react";
import { DocumentSetSummary, Tag, ValidSources } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import { FiBook, FiBookmark, FiMap, FiX } from "react-icons/fi";
import { SearchDateRangeSelector } from "@/components/dateRangeSelectors/SearchDateRangeSelector";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { listSourceMetadata } from "@/lib/sources";
import { SourceIcon } from "@/components/SourceIcon";
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
