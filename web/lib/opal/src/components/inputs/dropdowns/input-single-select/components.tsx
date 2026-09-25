"use client";

import { SingleDropdown } from "@opal/components/inputs/dropdowns/single/components";
import type { InputSingleSelectProps } from "@opal/components/inputs/dropdowns/types";

/**
 * A single pick from a set, with nothing to type: like a native `<select>`,
 * a click or ArrowDown opens the full set, a second click closes it, and
 * focus alone does not open it. Re-picking the selected option unselects
 * it; with a `defaultOption` the select never reads as empty. The family's
 * type-in sibling is `InputSingleComboBox`.
 */
function InputSingleSelect(props: InputSingleSelectProps) {
  return <SingleDropdown {...props} trigger="button" />;
}

export { InputSingleSelect };
