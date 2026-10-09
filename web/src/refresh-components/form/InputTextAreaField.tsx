"use client";

import { useField } from "formik";
import { InputTextArea, type InputTextAreaProps } from "@opal/components";
import { useOnChangeEvent, useOnBlurEvent } from "@/hooks/formHooks";

export interface InputTextAreaFieldProps extends Omit<
  InputTextAreaProps,
  "value"
> {
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
  const isNonEditable =
    textareaProps.variant === "disabled" ||
    textareaProps.variant === "readOnly";

  return (
    <InputTextArea
      {...textareaProps}
      id={name}
      name={name}
      value={field.value ?? ""}
      onChange={onChange}
      onBlur={onBlur}
      variant={
        isNonEditable
          ? textareaProps.variant
          : hasError
            ? "error"
            : textareaProps.variant
      }
    />
  );
}
