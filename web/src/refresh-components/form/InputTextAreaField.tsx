"use client";

import { useField } from "formik";
import InputTextArea, {
  InputTextAreaProps,
} from "@/refresh-components/inputs/InputTextArea";
import { useOnChange } from "@/hooks/useFormInputChange";

export interface InputTextAreaFieldProps
  extends Omit<InputTextAreaProps, "value" | "onChange"> {
  name: string;
}

export default function InputTextAreaField({
  name,
  ...textareaProps
}: InputTextAreaFieldProps) {
  const [field, meta] = useField(name);
  const onChange = useOnChange(name);
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
