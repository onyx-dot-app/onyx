"use client";

import { useField } from "formik";
import { InputMultiSelect, type InputMultiSelectProps } from "@opal/components";

export interface InputMultiSelectFieldProps extends Omit<
  InputMultiSelectProps,
  "value" | "onChange"
> {
  /** Formik field name; the field's value is the selected-id array. */
  name: string;
}

/**
 * `InputMultiSelect` bound to a Formik `string[]` field. The base component
 * stays controlled and Formik-free; this wrapper supplies the array value
 * and writes toggles back through the field helpers.
 */
export function InputMultiSelectField({
  name,
  ...inputProps
}: InputMultiSelectFieldProps) {
  const [field, , helpers] = useField<string[]>(name);

  return (
    <InputMultiSelect
      {...inputProps}
      id={name}
      name={name}
      value={field.value ?? []}
      onChange={(next) => void helpers.setValue(next)}
    />
  );
}
