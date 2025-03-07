import { SourceIcon } from "@/components/SourceIcon";
import React from "react";
import { FiBookmark, FiTag, FiX } from "react-icons/fi";
import { FilterManager } from "@/lib/hooks";
import { DateRangePickerValue } from "@/app/ee/admin/performance/DateRangeSelector";

const displayTimeRange = (timeRange: DateRangePickerValue) => {
  if (timeRange.selectValue) {
    return timeRange.selectValue;
  }

  if (timeRange.from && timeRange.to) {
    return `${timeRange.from.toLocaleDateString()} to ${timeRange.to.toLocaleDateString()}`;
  } else if (timeRange.from) {
    return `From ${timeRange.from.toLocaleDateString()}`;
  } else if (timeRange.to) {
    return `Until ${timeRange.to.toLocaleDateString()}`;
  } else {
    return "No date range selected";
  }
};

const SelectedFilter = ({
  onClick,
  children,
}: {
  onClick: () => void;
  children: JSX.Element | string;
}) => (
  <div
    className="
      flex 
      text-xs 
      cursor-pointer 
      items-center 
      border 
      border-border 
      py-1 
      rounded-lg 
      px-2 
      w-fit 
      select-none 
      hover:bg-accent-background-hovered 
      bg-background 
      shadow-md 
    "
    onClick={onClick}
  >
    {children}
    <FiX className="ml-2" size={14} />
  </div>
);

export function SelectedFilterDisplay({
  filterManager,
}: {
  filterManager: FilterManager;
}) {
  const {
    timeRange,
    setTimeRange,
    selectedSources,
    setSelectedSources,
    selectedDocumentSets,
    setSelectedDocumentSets,
    selectedTags,
    setSelectedTags,
  } = filterManager;

  const anyFilters =
    timeRange !== null ||
    selectedSources.length > 0 ||
    selectedDocumentSets.length > 0 ||
    selectedTags.length > 0;

  if (!anyFilters) {
    return null;
  }

  return (
    <div className="flex mb-2">
      <div className="flex flex-wrap gap-x-2">
        {timeRange &&
          (timeRange.selectValue || timeRange.from || timeRange.to) && (
            <SelectedFilter onClick={() => setTimeRange(null)}>
              <div className="flex">{displayTimeRange(timeRange)}</div>
            </SelectedFilter>
          )}
        {selectedSources.map((source) => (
          <SelectedFilter
            key={source.internalName}
            onClick={() =>
              setSelectedSources((prevSources) =>
                prevSources.filter(
                  (s) => s.internalName !== source.internalName
                )
              )
            }
          >
            <>
              <SourceIcon sourceType={source.internalName} iconSize={16} />
              <span className="ml-2">{source.displayName}</span>
            </>
          </SelectedFilter>
        ))}
        {selectedDocumentSets.length > 0 &&
          selectedDocumentSets.map((documentSetName) => (
            <SelectedFilter
              key={documentSetName}
              onClick={() =>
                setSelectedDocumentSets((prevSets) =>
                  prevSets.filter((s) => s !== documentSetName)
                )
              }
            >
              <>
                <div>
                  <FiBookmark />
                </div>
                <span className="ml-2">{documentSetName}</span>
              </>
            </SelectedFilter>
          ))}
        {selectedTags.length > 0 &&
          selectedTags.map((tag) => (
            <SelectedFilter
              key={tag.tag_key + tag.tag_value}
              onClick={() =>
                setSelectedTags((prevTags) =>
                  prevTags.filter(
                    (t) =>
                      t.tag_key !== tag.tag_key || t.tag_value !== tag.tag_value
                  )
                )
              }
            >
              <>
                <div>
                  <FiTag />
                </div>
                <span className="ml-1 max-w-[100px] text-ellipsis line-clamp-1 break-all">
                  {tag.tag_key}
                  <b>=</b>
                  {tag.tag_value}
                </span>
              </>
            </SelectedFilter>
          ))}
      </div>
    </div>
  );
}
