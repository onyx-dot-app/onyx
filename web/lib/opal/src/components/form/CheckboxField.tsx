"use client";

import { useField } from "formik";
import { Checkbox, type CheckboxProps } from "@opal/components";
import { useOnChangeValue } from "./hooks";

export interface CheckboxFieldProps extends Omit<CheckboxProps, "checked"> {
  name: string;
}

export function CheckboxField({
  name,
  onCheckedChange,
  ...props
}: CheckboxFieldProps) {
  const [field] = useField<boolean>({ name, type: "checkbox" });
  const onChange = useOnChangeValue(name, onCheckedChange);

  return (
    <Checkbox checked={field.value} onCheckedChange={onChange} {...props} />
  );
}
