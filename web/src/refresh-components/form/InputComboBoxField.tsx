"use client";

import { useField } from "formik";
import {
  InputSingleSelect,
  type InputSingleSelectProps,
} from "@opal/components";
import { useOnChangeEvent, useOnChangeValue } from "@/hooks/formHooks";

/**
 * Formik-bound version of `InputSingleSelect`. Use this inside a `<Formik>` form
 * when you need a combo box (free-text input with dropdown suggestions).
 * For a plain combo box without Formik binding, use `InputSingleSelect` directly.
 */
export interface InputComboBoxFieldProps extends Omit<
  InputSingleSelectProps,
  "value"
> {
  name: string;
}

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
