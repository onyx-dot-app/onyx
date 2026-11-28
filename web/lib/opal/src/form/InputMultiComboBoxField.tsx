"use client";

import { InputMultiComboBox } from "@opal/components/inputs/dropdowns/input-multi-combo-box/components";
import type { InputMultiComboBoxProps } from "@opal/components/inputs/dropdowns/types";
import { useMultiDropdownField } from "@opal/form/dropdownFields";

/**
 * Every `InputMultiComboBox` prop except the selection and the filter text,
 * which the field owns.
 */
type InputMultiComboBoxFieldProps = Omit<
  InputMultiComboBoxProps,
  "tags" | "onSelectOption" | "onRemoveTag" | "value" | "onChange" | "onAdd"
> & {
  /** The Formik field name. Its value is `string[]` of option values. */
  name: string;
};

/**
 * Formik-bound `InputMultiComboBox`. A pick appends the option value to the
 * field, unpicking or removing a chip drops it, and both mark the field
 * touched. With `mode="open"` the create row appends the raw text. The
 * filter text is local state.
 */
function InputMultiComboBoxField({
  name,
  options,
  variant,
  ...comboBoxProps
}: InputMultiComboBoxFieldProps) {
  const bound = useMultiDropdownField(
    name,
    options,
    comboBoxProps.mode === "open"
  );
  return (
    <InputMultiComboBox
      {...comboBoxProps}
      variant={bound.isError ? "error" : variant}
      tags={bound.tags}
      options={options}
      value={bound.filter}
      onChange={bound.setFilter}
      onAdd={bound.add}
      onSelectOption={bound.onSelectOption}
      onRemoveTag={bound.remove}
    />
  );
}

export { InputMultiComboBoxField, type InputMultiComboBoxFieldProps };
