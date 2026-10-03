"use client";

import React from "react";
import { LineItemButton } from "@opal/components/buttons/line-item-button/components";
import { optionElementId } from "@opal/components/dropdown/model";
import type { DropdownOption } from "@opal/components/dropdown/types";

interface OptionRowProps {
  listId: string;
  option: DropdownOption;
  /** The row's keyboard stop, or -1 while it is withheld (folded). */
  index: number;
  isHighlighted: boolean;
  isSelected: boolean;
  onSelect: (option: DropdownOption) => void;
}

/**
 * One row of the list: a presentational `LineItemButton`, since the list
 * owns focus and the keyboard and addresses the row through
 * `aria-activedescendant`. The selection reads as the selected state; the
 * keyboard stop reads as hover. Memoized: the list re-renders on every
 * highlight move.
 */
export const OptionRow = React.memo(function OptionRow({
  listId,
  option,
  index,
  isHighlighted,
  isSelected,
  onSelect,
}: OptionRowProps) {
  return (
    <LineItemButton
      presentational
      selectVariant="select-heavy"
      state={isSelected ? "selected" : "empty"}
      interaction={isHighlighted ? "hover" : "rest"}
      disabled={option.disabled}
      rounding={2}
      icon={option.icon}
      title={option.title}
      description={option.description}
      suffix={option.suffix}
      sizePreset="main-ui"
      // `body` resolves to `ContentSm`, which has no description or suffix
      // slot; a row with either takes the `heading` layout.
      variant={option.description || option.suffix ? "heading" : "body"}
      id={optionElementId(listId, option.value)}
      data-index={index}
      role="option"
      tabIndex={-1}
      aria-selected={isSelected}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(option);
      }}
      onMouseDown={(e) => {
        // Keep focus on the trigger: the pick must not blur it.
        e.preventDefault();
      }}
    />
  );
});
