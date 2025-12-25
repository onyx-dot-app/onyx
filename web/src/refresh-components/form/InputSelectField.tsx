"use client";

import { useField } from "formik";
import InputSelect, {
  InputSelectRootProps,
} from "@/refresh-components/inputs/InputSelect";
import { useFormInputCallback } from "@/hooks/formHooks";

export interface InputSelectFieldProps
  extends Omit<InputSelectRootProps, "value"> {
  name: string;
}

export default function InputSelectField({
  name,
  children,
  onValueChange,
  ...selectProps
}: InputSelectFieldProps) {
  const [field, meta] = useField(name);
  const onChange = useFormInputCallback(name, onValueChange);
  const hasError = meta.touched && meta.error;

  return (
    <InputSelect
      value={field.value}
      onValueChange={onChange}
      error={!!hasError}
      {...selectProps}
    >
      {children}
    </InputSelect>
  );
}
