"use client";

import { useField } from "formik";
import InputTextArea, {
  InputTextAreaProps,
} from "@/refresh-components/inputs/InputTextArea";
import { useFormInputCallback } from "@/hooks/formHooks";

export interface InputTextAreaFieldProps
  extends Omit<InputTextAreaProps, "value"> {
  name: string;
}

export default function InputTextAreaField({
  name,
  onChange: onChangeProp,
  ...textareaProps
}: InputTextAreaFieldProps) {
  const [field, meta] = useField(name);
  const onChange = useFormInputCallback(name, onChangeProp);
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
