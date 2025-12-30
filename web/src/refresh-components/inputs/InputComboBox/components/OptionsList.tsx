import React from "react";
import Text from "@/refresh-components/texts/Text";
import { OptionItem } from "./OptionItem";
import { ComboBoxOption } from "../types";

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
}) => {
  if (matchedOptions.length === 0 && unmatchedOptions.length === 0) {
    return (
      <div className="px-3 py-2 text-text-02 font-secondary-body">
        No options found
      </div>
    );
  }

  return (
    <>
      {/* Matched/Filtered Options */}
      {matchedOptions.map((option, idx) => {
        const globalIndex = idx;
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
        const globalIndex = matchedOptions.length + idx;
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
          />
        );
      })}
    </>
  );
};
