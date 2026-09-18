"use client";

import { useField } from "formik";
import {
  InputSingleSelect,
  type InputSingleSelectProps,
} from "@opal/components";
import type { DistributiveOmit } from "@opal/types";
import { useOnChangeEvent, useOnChangeValue } from "@/hooks/formHooks";

/**
 * Formik-bound version of `InputSingleSelect`. Use this inside a `<Formik>` form
 * when you need a combo box (free-text input with dropdown suggestions).
 * For a plain combo box without Formik binding, use `InputSingleSelect` directly.
 */
// DistributiveOmit keeps the mode/options union arms intact — a plain Omit
// (or interface extends) would collapse them and un-enforce the pairing.
export type InputComboBoxFieldProps = DistributiveOmit<
  InputSingleSelectProps,
  "value"
> & {
  name: string;
};

export default function InputComboBoxField({
  name,
  onChange: onChangeProp,
  onValueChange: onValueChangeProp,
  ...inputProps
}: InputComboBoxFieldProps) {
  const [field, meta] = useField<string>(name);
  const onChange = useOnChangeEvent(name, onChangeProp);
  const onValueChange = useOnChangeValue(name, onValueChangeProp);
  const hasError = meta.touched && meta.error;

  return (
    <InputSingleSelect
      {...inputProps}
      name={name}
      value={field.value ?? ""}
      onChange={onChange}
      onValueChange={onValueChange}
      isError={hasError ? true : inputProps.isError}
    />
  );
}
