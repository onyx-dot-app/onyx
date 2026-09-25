import React from "react";
import { LineItemButton } from "@opal/components/buttons/line-item-button/components";
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
  /** The pointer moved over the row: the keyboard highlight yields. */
  onMouseMove: () => void;
}

/**
 * One row of the listbox: a presentational `LineItemButton`, since the
 * listbox owns focus and the keyboard and addresses the row through
 * `aria-activedescendant`. Selection and the exact match read as the
 * selected state; the keyboard stop reads as hover. Memoized to prevent
 * unnecessary re-renders.
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
    onMouseMove,
  }: OptionItemProps) => {
    return (
      <LineItemButton
        presentational
        selectVariant="select-heavy"
        state={isSelected || isExact ? "selected" : "empty"}
        interaction={isHighlighted ? "hover" : "rest"}
        disabled={option.disabled}
        rounding={2}
        icon={option.icon}
        title={option.title}
        description={option.description}
        sizePreset="main-ui"
        variant="body"
        id={`${fieldId}-option-${sanitizeOptionId(option.value)}`}
        data-index={index}
        role="option"
        tabIndex={-1}
        aria-selected={isSelected}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(option);
        }}
        onMouseDown={(e) => {
          e.preventDefault();
        }}
        onMouseMove={onMouseMove}
      />
    );
  }
);

OptionItem.displayName = "OptionItem";
