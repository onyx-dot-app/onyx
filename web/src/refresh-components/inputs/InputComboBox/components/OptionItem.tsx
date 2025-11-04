import React from "react";
import { cn } from "@/lib/utils";
import { ComboBoxOption } from "../types";

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
}

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
  }: OptionItemProps) => {
    return (
      <div
        id={`${fieldId}-option-${option.value}`}
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
          {option.label}
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
