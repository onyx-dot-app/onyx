"use client";

import { InputSingleSelect } from "@opal/components/inputs/dropdowns/input-single-select/components";
import type { InputSingleSelectProps } from "@opal/components/inputs/dropdowns/types";
import type { DistributiveOmit } from "@opal/types";
import { useSingleDropdownField } from "@opal/form/dropdownFields";

/** Every `InputSingleSelect` prop except the value, which Formik owns. */
type InputSingleSelectFieldProps = DistributiveOmit<
  InputSingleSelectProps,
  "value" | "isError"
> & {
  /** The Formik field name. */
  name: string;
};

/**
 * Formik-bound `InputSingleSelect`. A pick writes the option value to the
 * field and marks it touched; a touched field with an error shows the error
 * state. `onValueChange` still fires after the field is updated.
 */
function InputSingleSelectField({
  name,
  onValueChange,
  ...selectProps
}: InputSingleSelectFieldProps) {
  const bound = useSingleDropdownField(name, onValueChange);
  return <InputSingleSelect {...selectProps} name={name} {...bound} />;
}

export { InputSingleSelectField, type InputSingleSelectFieldProps };
