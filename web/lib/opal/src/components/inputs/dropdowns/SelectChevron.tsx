"use client";

import { Button } from "@opal/components/buttons/button/components";
import { ChevronIcon } from "@opal/components/buttons/chevron";
import { useOpalStrings } from "@opal/strings";

interface SelectChevronProps {
  isOpen: boolean;
  disabled?: boolean;
  onToggle: () => void;
}

/**
 * The family's dropdown toggle. Swallows mousedown so focus never leaves
 * the trigger input — otherwise the trailing focus() after a toggle-close
 * re-opens the dropdown through onFocus (a close/open flash).
 */
export function SelectChevron({
  isOpen,
  disabled,
  onToggle,
}: SelectChevronProps) {
  const strings = useOpalStrings();
  return (
    <Button
      disabled={disabled}
      prominence="tertiary"
      size="sm"
      icon={ChevronIcon}
      interaction={isOpen ? "hover" : undefined}
      aria-label={isOpen ? strings.comboBoxClose : strings.comboBoxOpen}
      tabIndex={-1}
      type="button"
      onMouseDown={(event) => event.preventDefault()}
      onClick={(event) => {
        event.stopPropagation();
        onToggle();
      }}
    />
  );
}
