"use client";

import { InputSingleComboBox } from "@opal/components/inputs/dropdowns/input-single-combo-box/components";
import type { InputSingleComboBoxProps } from "@opal/components/inputs/dropdowns/types";
import { useSingleDropdownField } from "@opal/form/dropdownFields";

/** Every `InputSingleComboBox` prop except the value, which Formik owns. */
type InputSingleComboBoxFieldProps = Omit<
  InputSingleComboBoxProps,
  "value" | "isError"
> & {
  /** The Formik field name. */
  name: string;
};

/**
 * Formik-bound `InputSingleComboBox`. A pick (or a create-row commit) writes
 * the option value to the field and marks it touched; keystrokes only
 * filter. A touched field with an error shows the error state.
 */
function InputSingleComboBoxField({
  name,
  onValueChange,
  ...comboBoxProps
}: InputSingleComboBoxFieldProps) {
  const bound = useSingleDropdownField(name, onValueChange);
  return <InputSingleComboBox {...comboBoxProps} name={name} {...bound} />;
}

export { InputSingleComboBoxField, type InputSingleComboBoxFieldProps };
