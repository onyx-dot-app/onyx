"use client";

import { useField } from "formik";
import InputSelect, {
  InputSelectRootProps,
} from "@/refresh-components/inputs/InputSelect";
import { useOnChange } from "@/hooks/useFormInputChange";

export interface InputSelectFieldProps
  extends Omit<InputSelectRootProps, "value" | "onValueChange"> {
  name: string;
}

export default function InputSelectField({
  name,
  children,
  ...selectProps
}: InputSelectFieldProps) {
  const [field, meta] = useField(name);
  const onValueChange = useOnChange(name);
  const hasError = meta.touched && meta.error;

  return (
    <InputSelect
      value={field.value}
      onValueChange={onValueChange}
      error={!!hasError}
      {...selectProps}
    >
      {children}
    </InputSelect>
  );
}
