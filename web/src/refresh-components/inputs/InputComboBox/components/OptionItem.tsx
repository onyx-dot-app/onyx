import React from "react";
import { cn } from "@/lib/utils";
import { ComboBoxOption } from "../types";
import { sanitizeOptionId } from "../utils/aria";

interface OptionItemProps {
  option: ComboBoxOption;
  index: number;
  fieldId: string;
  isHighlighted: boolean;
  isSelected: boolean;
  isExact: boolean;
  onSelect: (option: ComboBoxOption) => void;
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
      <span key={i} className="font-semibold">
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
        aria-selected={isSelected}
        aria-disabled={option.disabled}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(option);
        }}
        onMouseDown={(e) => {
          e.preventDefault();
        }}
        onMouseEnter={() => onMouseEnter(index)}
        onMouseMove={onMouseMove}
        className={cn(
          "px-3 py-2 cursor-pointer transition-colors",
          "flex flex-col rounded-08",
          isExact && "bg-action-link-01",
          !isExact && isHighlighted && "bg-background-tint-02",
          !isExact && isSelected && "bg-background-tint-02",
          option.disabled &&
            "opacity-50 cursor-not-allowed bg-background-neutral-02",
          !option.disabled && !isExact && "hover:bg-background-tint-02"
        )}
      >
        <span
          className={cn(
            "font-main-ui-action",
            isExact && "text-action-link-05 font-medium",
            !isExact && "text-text-04",
            !isExact && isSelected && "font-medium"
          )}
        >
          {highlightMatch(option.label, searchTerm)}
        </span>
        {option.description && (
          <span
            className={cn(
              "mt-0.5 font-secondary-body",
              isExact ? "text-action-link-04" : "text-text-03"
            )}
          >
            {option.description}
          </span>
        )}
      </div>
    );
  }
);

OptionItem.displayName = "OptionItem";
