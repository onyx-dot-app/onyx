/* import React from "react";
import { DocumentSet, Tag, ValidSources } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import { InfoIcon, defaultTailwindCSS } from "../../icons/icons";
import { HoverPopup } from "../../HoverPopup";
import { FiBook, FiBookmark, FiFilter, FiMap, FiX } from "react-icons/fi";
import { DateRangeSelector } from "../DateRangeSelector";
import { DateRangePickerValue } from "@tremor/react";
import { FilterDropdown } from "./FilterDropdown";
import { listSourceMetadata } from "@/lib/sources";
import { SourceIcon } from "@/components/SourceIcon";
import { TagFilter } from "./TagFilter";

const SectionTitle = ({ children }: { children: string }) => (
  <div className="flex mt-2 text-xs font-bold">{children}</div>
);

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
  availableDocumentSets: DocumentSet[];
  existingSources: ValidSources[];
  availableTags: Tag[];
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

  return (
    <div>
      <div className="flex pb-2 mb-4 border-b border-border text-emphasis">
        <h2 className="my-auto font-bold">Filters</h2>
        <FiFilter className="my-auto ml-2" size="16" />
      </div>

      <>
        <SectionTitle>Time Range</SectionTitle>
        <div className="mt-2">
          <DateRangeSelector value={timeRange} onValueChange={setTimeRange} />
        </div>
      </>

      {existingSources.length > 0 && (
        <div className="mt-4">
          <SectionTitle>Sources</SectionTitle>
          <div className="px-1">
            {listSourceMetadata()
              .filter((source) => existingSources.includes(source.internalName))
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
                  <SourceIcon sourceType={source.internalName} iconSize={16} />
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
                      <div className="w-64 text-sm">
                        <div className="flex font-medium">Description</div>
                        <div className="mt-1">{documentSet.description}</div>
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

      {availableTags.length > 0 && (
        <>
          <div className="mt-4 mb-2">
            <SectionTitle>Tags</SectionTitle>
          </div>
          <TagFilter
            tags={availableTags}
            selectedTags={selectedTags}
            setSelectedTags={setSelectedTags}
          />
        </>
      )}
    </div>
  );
}

function SelectedBubble({
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
      <div className="flex flex-col gap-3 md:flex-row">
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

      <div className="flex h-12 pb-4 mt-2">
        <div className="flex flex-wrap gap-x-2">
          {timeRange && timeRange.selectValue && (
            <SelectedBubble onClick={() => setTimeRange(null)}>
              <div className="flex text-sm">{timeRange.selectValue}</div>
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
} */

import React from "react";
import { DocumentSet, Tag, ValidSources } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import { InfoIcon, defaultTailwindCSS } from "../../icons/icons";
import { HoverPopup } from "../../HoverPopup";
import { FiBook, FiBookmark, FiFilter, FiMap, FiX } from "react-icons/fi";
import { DateRangeSelector } from "../DateRangeSelector";
import { DateRangePickerValue } from "@tremor/react";
import { FilterDropdown } from "./FilterDropdown";
import { listSourceMetadata } from "@/lib/sources";
import { SourceIcon } from "@/components/SourceIcon";
import { TagFilter } from "./TagFilter";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const SectionTitle = ({ children }: { children: string }) => (
  <div className="flex mt-2 text-xs font-bold">{children}</div>
);

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
  availableDocumentSets: DocumentSet[];
  existingSources: ValidSources[];
  availableTags: Tag[];
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

  return (
    <div>
      <div className="flex pb-2 mb-4 border-b border-border text-emphasis">
        <h2 className="my-auto font-bold">Filters</h2>
        <FiFilter className="my-auto ml-2" size="16" />
      </div>

      <>
        <SectionTitle>Time Range</SectionTitle>
        <div className="mt-2">
          <DateRangeSelector value={timeRange} onValueChange={setTimeRange} />
        </div>
      </>

      {existingSources.length > 0 && (
        <div className="mt-4">
          <SectionTitle>Sources</SectionTitle>
          <div className="px-1">
            {listSourceMetadata()
              .filter((source) => existingSources.includes(source.internalName))
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
                  <SourceIcon sourceType={source.internalName} iconSize={16} />
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
                      <div className="w-64 text-sm">
                        <div className="flex font-medium">Description</div>
                        <div className="mt-1">{documentSet.description}</div>
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

      {availableTags.length > 0 && (
        <>
          <div className="mt-4 mb-2">
            <SectionTitle>Tags</SectionTitle>
          </div>
          <TagFilter
            tags={availableTags}
            selectedTags={selectedTags}
            setSelectedTags={setSelectedTags}
          />
        </>
      )}
    </div>
  );
}

function SelectedBubble({
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
      <div className="flex flex-col gap-3 md:flex-row">
        <div className="w-64">
          <DateRangeSelector value={timeRange} onValueChange={setTimeRange} />
        </div>

        {/* <FilterDropdown
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
        /> */}
        <Select
          onValueChange={(value) => {
            const selectedSource = allSources.find(
              (source) => source.displayName === value
            );
            if (selectedSource) handleSourceSelect(selectedSource);
          }}
        >
          <SelectTrigger className="w-64">
            <div className="flex items-center gap-3">
              <FiMap size={16} />
              <SelectValue placeholder="All Sources" />
            </div>
          </SelectTrigger>
          <SelectContent>
            {availableSources.map((source) => (
              <SelectItem key={source.displayName} value={source.displayName}>
                <div className="flex items-center">
                  <SourceIcon sourceType={source.internalName} iconSize={16} />
                  <span className="ml-2 text-sm">{source.displayName}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* <FilterDropdown
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
        /> */}

        <Select
          onValueChange={(value) => handleDocumentSetSelect(value)}
          defaultValue=""
        >
          <SelectTrigger className="w-64">
            <div className="flex items-center gap-3">
              <FiBook size={16} />
              <SelectValue placeholder="All Document Sets" />
            </div>
          </SelectTrigger>
          <SelectContent>
            {availableDocumentSets.map((documentSet) => (
              <SelectItem
                key={documentSet.name}
                value={documentSet.name}
                className="flex items-center"
              >
                <div className="my-auto">
                  <FiBookmark />
                </div>
                <span className="ml-2 text-sm">{documentSet.name}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex h-12 pb-4 mt-2">
        <div className="flex flex-wrap gap-x-2">
          {timeRange && timeRange.selectValue && (
            <SelectedBubble onClick={() => setTimeRange(null)}>
              <div className="flex text-sm">{timeRange.selectValue}</div>
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
