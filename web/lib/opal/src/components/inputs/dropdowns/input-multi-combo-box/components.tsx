"use client";

import { MultiDropdown } from "@opal/components/inputs/dropdowns/multi/components";
import type { InputMultiComboBoxProps } from "@opal/components/inputs/dropdowns/types";

/**
 * Several picks from a set behind a text input: chips beside a field whose
 * text filters the options, and `mode="open"` also commits the raw text via
 * the create row. Focus opens the list. The family's pick-only sibling is
 * `InputMultiSelect`.
 */
function InputMultiComboBox(props: InputMultiComboBoxProps) {
  return <MultiDropdown {...props} trigger="type-in" />;
}

export { InputMultiComboBox };
