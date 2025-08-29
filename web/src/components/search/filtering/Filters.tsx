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

const SectionTitle = ({ children }: { children: string }) => (
  <div className="font-bold text-xs mt-2 flex">{children}</div>
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
      <div className="flex mb-4 pb-2 border-b border-border text-emphasis">
        <h2 className="font-bold my-auto">Фильтры</h2>
        <FiFilter className="my-auto ml-2" size="16" />
      </div>

      <>
        <SectionTitle>Период</SectionTitle>
        <div className="mt-2">
          <DateRangeSelector value={timeRange} onValueChange={setTimeRange} />
        </div>
      </>

      {existingSources.length > 0 && (
        <div className="mt-4">
          <SectionTitle>Источники данных</SectionTitle>
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
            <SectionTitle>Наборы документов</SectionTitle>
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
                        <div className="flex font-medium">Описание</div>
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
            <SectionTitle>Теги</SectionTitle>
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
          defaultDisplay="Все источники данных"
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
          defaultDisplay="Все наборы документов"
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
