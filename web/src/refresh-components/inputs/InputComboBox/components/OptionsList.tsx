import React from "react";
import Text from "@/refresh-components/texts/Text";
import { OptionItem } from "./OptionItem";
import { ComboBoxOption } from "../types";
import { cn } from "@/lib/utils";
import { SvgPlus } from "@opal/icons";
import { sanitizeOptionId } from "../utils/aria";

interface OptionsListProps {
  matchedOptions: ComboBoxOption[];
  unmatchedOptions: ComboBoxOption[];
  hasSearchTerm: boolean;
  separatorLabel: string;
  value: string;
  highlightedIndex: number;
  fieldId: string;
  onSelect: (option: ComboBoxOption) => void;
  onMouseEnter: (index: number) => void;
  onMouseMove: () => void;
  isExactMatch: (option: ComboBoxOption) => boolean;
  /** Current input value for creating new option */
  inputValue: string;
  /** Whether to show create option when no exact match */
  allowCreate: boolean;
  /** Whether to show create option (pre-computed by parent) */
  showCreateOption: boolean;
}

/**
 * Renders the list of options with matched/unmatched sections
 * Includes separator between sections when filtering
 */
export const OptionsList: React.FC<OptionsListProps> = ({
  matchedOptions,
  unmatchedOptions,
  hasSearchTerm,
  separatorLabel,
  value,
  highlightedIndex,
  fieldId,
  onSelect,
  onMouseEnter,
  onMouseMove,
  isExactMatch,
  inputValue,
  allowCreate,
  showCreateOption,
}) => {
  // Index offset for other options when create option is shown
  const indexOffset = showCreateOption ? 1 : 0;

  if (
    matchedOptions.length === 0 &&
    unmatchedOptions.length === 0 &&
    !showCreateOption
  ) {
    return (
      <div className="px-3 py-2 text-text-02 font-secondary-body">
        No options found
      </div>
    );
  }

  return (
    <>
      {/* Create New Option */}
      {showCreateOption && (
        <div
          id={`${fieldId}-option-${sanitizeOptionId(inputValue)}`}
          data-index={0}
          role="option"
          aria-selected={false}
          aria-label={`Create "${inputValue}"`}
          onClick={(e) => {
            e.stopPropagation();
            onSelect({ value: inputValue, label: inputValue });
          }}
          onMouseDown={(e) => {
            e.preventDefault();
          }}
          onMouseEnter={() => onMouseEnter(0)}
          onMouseMove={onMouseMove}
          className={cn(
            "px-3 py-2 cursor-pointer transition-colors",
            "flex items-center justify-between rounded-08",
            highlightedIndex === 0 && "bg-background-tint-02",
            "hover:bg-background-tint-02"
          )}
        >
          <span className="font-main-ui-action text-text-04 truncate min-w-0">
            {inputValue}
          </span>
          <SvgPlus className="w-4 h-4 text-text-03 flex-shrink-0 ml-2" />
        </div>
      )}

      {/* Matched/Filtered Options */}
      {matchedOptions.map((option, idx) => {
        const globalIndex = idx + indexOffset;
        // Only highlight first exact match, not all matches
        const isExact = idx === 0 && isExactMatch(option);
        return (
          <OptionItem
            key={option.value}
            option={option}
            index={globalIndex}
            fieldId={fieldId}
            isHighlighted={globalIndex === highlightedIndex}
            isSelected={value === option.value}
            isExact={isExact}
            onSelect={onSelect}
            onMouseEnter={onMouseEnter}
            onMouseMove={onMouseMove}
            searchTerm={inputValue}
          />
        );
      })}

      {/* Separator - only show if there are unmatched options and a search term */}
      {hasSearchTerm && unmatchedOptions.length > 0 && (
        <div className="px-3 py-2 pt-3">
          <div className="border-t border-border-01 pt-2">
            <Text as="p" text04 secondaryBody className="text-text-02">
              {separatorLabel}
            </Text>
          </div>
        </div>
      )}

      {/* Unmatched Options */}
      {unmatchedOptions.map((option, idx) => {
        const globalIndex = matchedOptions.length + idx + indexOffset;
        const isExact = isExactMatch(option);
        return (
          <OptionItem
            key={option.value}
            option={option}
            index={globalIndex}
            fieldId={fieldId}
            isHighlighted={globalIndex === highlightedIndex}
            isSelected={value === option.value}
            isExact={isExact}
            onSelect={onSelect}
            onMouseEnter={onMouseEnter}
            onMouseMove={onMouseMove}
            searchTerm={inputValue}
          />
        );
      })}
    </>
  );
};
