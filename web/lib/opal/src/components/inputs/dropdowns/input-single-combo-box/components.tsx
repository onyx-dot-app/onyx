"use client";

import { SingleDropdown } from "@opal/components/inputs/dropdowns/single/components";
import type { InputSingleComboBoxProps } from "@opal/components/inputs/dropdowns/types";

/**
 * A single pick from a set behind a text input: typing filters the options,
 * and `mode="open"` also commits the raw text via the create row. Focus
 * opens the list. The family's pick-only sibling is `InputSingleSelect`.
 */
function InputSingleComboBox(props: InputSingleComboBoxProps) {
  return <SingleDropdown {...props} trigger="type-in" />;
}

export { InputSingleComboBox };
