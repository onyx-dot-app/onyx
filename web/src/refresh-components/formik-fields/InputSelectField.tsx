"use client";

import { useField } from "formik";
import InputSelect, {
  InputSelectRootProps,
} from "@/refresh-components/inputs/InputSelect";

export interface InputSelectFieldProps
  extends Omit<InputSelectRootProps, "value" | "onValueChange"> {
  name: string;
  onValueChange?: (value: string) => void;
}

export default function InputSelectField({
  name,
  onValueChange,
  children,
  ...selectProps
}: InputSelectFieldProps) {
  const [field, meta, helpers] = useField(name);
  const hasError = meta.touched && meta.error;

  return (
    <InputSelect
      value={field.value}
      onValueChange={(value) => {
        helpers.setValue(value);
        helpers.setTouched(true);
        onValueChange?.(value);
      }}
      error={!!hasError}
      {...selectProps}
    >
      {children}
    </InputSelect>
  );
}
