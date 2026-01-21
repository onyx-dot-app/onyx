"use client";

import { useField } from "formik";
import InputSelect, {
  InputSelectRootProps,
} from "@/refresh-components/inputs/InputSelect";
import { useOnChangeValue } from "@/hooks/formHooks";

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
  const onChange = useOnChangeValue(name, onValueChange);
  const hasError = meta.touched && meta.error;

  return (
    <InputSelect
      name={name}
      value={field.value}
      onValueChange={onChange}
      error={!!hasError}
      {...selectProps}
    >
      {children}
    </InputSelect>
  );
}
