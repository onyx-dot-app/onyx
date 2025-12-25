"use client";

import { useField } from "formik";
import InputTextArea, {
  InputTextAreaProps,
} from "@/refresh-components/inputs/InputTextArea";
import { useFormInputCallback } from "@/hooks/form-hooks";

export interface InputTextAreaFieldProps
  extends Omit<InputTextAreaProps, "value" | "onChange"> {
  name: string;
}

export default function InputTextAreaField({
  name,
  ...textareaProps
}: InputTextAreaFieldProps) {
  const [field, meta] = useField(name);
  const onChange = useFormInputCallback(name);
  const hasError = meta.touched && meta.error;

  return (
    <InputTextArea
      {...textareaProps}
      id={name}
      name={name}
      value={field.value || ""}
      onChange={onChange}
      onBlur={field.onBlur}
      error={!!hasError}
    />
  );
}
