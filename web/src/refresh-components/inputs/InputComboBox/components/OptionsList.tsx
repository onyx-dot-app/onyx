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
  /** Prefix shown before the typed value in the create option (e.g., "Use", "Add") */
  createPrefix?: string;
}

/**
 * Renders the list of options with matched/unmatched sections
 * Includes divider between sections when filtering
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
  createPrefix,
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
          aria-label={`${createPrefix ?? "Create"} "${inputValue}"`}
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
            "cursor-pointer transition-colors",
            "flex items-center justify-between rounded-08",
            highlightedIndex === 0 && "bg-background-tint-02",
            "hover:bg-background-tint-02",
            createPrefix ? "px-1.5 py-1.5" : "px-3 py-2"
          )}
        >
          <span
            className={cn(
              "font-main-ui-action truncate min-w-0",
              createPrefix ? "px-1" : ""
            )}
          >
            {createPrefix ? (
              <>
                <span className="text-text-03">{createPrefix}</span>
                <span className="text-text-04">{` ${inputValue}`}</span>
              </>
            ) : (
              <span className="text-text-04">{inputValue}</span>
            )}
          </span>
          <SvgPlus
            className={cn(
              "w-4 h-4 flex-shrink-0",
              createPrefix ? "text-text-04 mx-1" : "text-text-03 ml-2"
            )}
          />
        </div>
      )}

      {/* Separator - show when there are options to display */}
      {separatorLabel &&
        (matchedOptions.length > 0 ||
          (!hasSearchTerm && unmatchedOptions.length > 0)) && (
          <div className="px-3 py-1">
            <Text as="p" text03 secondaryBody>
              {separatorLabel}
            </Text>
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

      {/* Unmatched Options - only show when NOT searching */}
      {!hasSearchTerm &&
        unmatchedOptions.map((option, idx) => {
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
