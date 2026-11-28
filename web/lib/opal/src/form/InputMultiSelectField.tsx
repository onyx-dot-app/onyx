"use client";

import { InputMultiSelect } from "@opal/components/inputs/dropdowns/input-multi-select/components";
import type { InputMultiSelectProps } from "@opal/components/inputs/dropdowns/types";
import { useMultiDropdownField } from "@opal/form/dropdownFields";

/** Every `InputMultiSelect` prop except the selection, which Formik owns. */
type InputMultiSelectFieldProps = Omit<
  InputMultiSelectProps,
  "tags" | "onSelectOption" | "onRemoveTag"
> & {
  /** The Formik field name. Its value is `string[]` of option values. */
  name: string;
};

/**
 * Formik-bound `InputMultiSelect`. A pick appends the option value to the
 * field, unpicking or removing a chip drops it, and both mark the field
 * touched. Chips take their labels from `options`.
 */
function InputMultiSelectField({
  name,
  options,
  variant,
  ...selectProps
}: InputMultiSelectFieldProps) {
  const bound = useMultiDropdownField(name, options, false);
  return (
    <InputMultiSelect
      {...selectProps}
      variant={bound.isError ? "error" : variant}
      tags={bound.tags}
      options={options}
      onSelectOption={bound.onSelectOption}
      onRemoveTag={bound.remove}
    />
  );
}

export { InputMultiSelectField, type InputMultiSelectFieldProps };
