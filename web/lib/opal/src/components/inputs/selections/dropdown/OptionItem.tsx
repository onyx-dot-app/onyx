import React from "react";
import { clickOnKeyDown } from "@opal/utils";
import { SelectOption } from "../types";
import { sanitizeOptionId } from "./aria";

interface OptionItemProps {
  option: SelectOption;
  index: number;
  fieldId: string;
  isHighlighted: boolean;
  isSelected: boolean;
  isExact: boolean;
  onSelect: (option: SelectOption) => void;
  onMouseEnter: (index: number) => void;
  onMouseMove: () => void;
  /** Search term to highlight in the label */
  searchTerm: string;
}

/**
 * Escapes special regex characters in a string
 */
const escapeRegex = (str: string) => str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Highlights matching text within a string
 */
const highlightMatch = (text: string, searchTerm: string): React.ReactNode => {
  if (!searchTerm.trim()) return text;

  const regex = new RegExp(`(${escapeRegex(searchTerm)})`, "gi");
  const parts = text.split(regex);

  if (parts.length === 1) return text;

  return parts.map((part, i) =>
    part.toLowerCase() === searchTerm.toLowerCase() ? (
      <span key={i} className="opal-select-match">
        {part}
      </span>
    ) : (
      part
    )
  );
};

/**
 * Renders a single option item in the dropdown
 * Memoized to prevent unnecessary re-renders
 */
export const OptionItem = React.memo(
  ({
    option,
    index,
    fieldId,
    isHighlighted,
    isSelected,
    isExact,
    onSelect,
    onMouseEnter,
    onMouseMove,
    searchTerm,
  }: OptionItemProps) => {
    return (
      <div
        id={`${fieldId}-option-${sanitizeOptionId(option.value)}`}
        data-index={index}
        role="option"
        tabIndex={-1}
        aria-selected={isSelected}
        aria-disabled={option.disabled}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(option);
        }}
        onKeyDown={clickOnKeyDown(() => onSelect(option))}
        onMouseDown={(e) => {
          e.preventDefault();
        }}
        onMouseEnter={() => onMouseEnter(index)}
        onMouseMove={onMouseMove}
        className="opal-select-option"
        data-exact={isExact || undefined}
        data-highlighted={isHighlighted || undefined}
        data-selected={isSelected || undefined}
        data-disabled={option.disabled || undefined}
      >
        <span className="opal-select-option-label">
          {option.icon && <option.icon className="opal-select-option-icon" />}
          <span className="opal-select-option-text">
            {highlightMatch(option.label, searchTerm)}
          </span>
        </span>
        {option.description && (
          <span className="opal-select-option-description">
            {option.description}
          </span>
        )}
      </div>
    );
  }
);

OptionItem.displayName = "OptionItem";
