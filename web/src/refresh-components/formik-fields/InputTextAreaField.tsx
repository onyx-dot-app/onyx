"use client";

import { useField } from "formik";
import InputTextArea, {
  InputTextAreaProps,
} from "@/refresh-components/inputs/InputTextArea";

export interface InputTextAreaFieldProps
  extends Omit<InputTextAreaProps, "value" | "onChange"> {
  name: string;
}

export default function InputTextAreaField({
  name,
  ...textareaProps
}: InputTextAreaFieldProps) {
  const [field, meta] = useField(name);
  const hasError = meta.touched && meta.error;

  return (
    <InputTextArea
      {...textareaProps}
      id={name}
      name={name}
      value={field.value || ""}
      onChange={field.onChange}
      onBlur={field.onBlur}
      error={!!hasError}
    />
  );
}
