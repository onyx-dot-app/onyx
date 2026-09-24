"use client";

import { MultiDropdown } from "@opal/components/inputs/dropdowns/multi/components";
import type { InputMultiSelectProps } from "@opal/components/inputs/dropdowns/types";

/**
 * Several picks from a set, with nothing to type: the chosen options are
 * chips that make up the whole field, a focusable combobox element takes the
 * keyboard, and the list always shows the full set. A click toggles it open
 * and closed; focus alone does not open it. The family's type-in sibling is
 * `InputMultiComboBox`.
 */
function InputMultiSelect(props: InputMultiSelectProps) {
  return <MultiDropdown {...props} trigger="button" />;
}

export { InputMultiSelect };
