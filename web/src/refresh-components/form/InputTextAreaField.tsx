"use client";

import { useField } from "formik";
import InputTextArea, {
  InputTextAreaProps,
} from "@/refresh-components/inputs/InputTextArea";
import { useOnChangeEvent, useOnBlurEvent } from "@/hooks/formHooks";

export interface InputTextAreaFieldProps
  extends Omit<InputTextAreaProps, "value"> {
  name: string;
}

export default function InputTextAreaField({
  name,
  onChange: onChangeProp,
  onBlur: onBlurProp,
  ...textareaProps
}: InputTextAreaFieldProps) {
  const [field, meta] = useField(name);
  const onChange = useOnChangeEvent(name, onChangeProp);
  const onBlur = useOnBlurEvent(name, onBlurProp);
  const hasError = meta.touched && meta.error;

  return (
    <InputTextArea
      {...textareaProps}
      id={name}
      name={name}
      value={field.value ?? ""}
      onChange={onChange}
      onBlur={onBlur}
      error={!!hasError}
    />
  );
}
