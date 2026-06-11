"use client";

import { useField } from "formik";
import { InputTypeIn, type InputTypeInProps } from "@opal/components";
import { useOnChangeEvent, useOnBlurEvent } from "@/hooks/formHooks";

export interface InputTypeInFieldProps extends Omit<InputTypeInProps, "value"> {
  name: string;
}

export default function InputTypeInField({
  name,
  onChange: onChangeProp,
  onBlur: onBlurProp,
  ...inputProps
}: InputTypeInFieldProps) {
  const [field, meta] = useField(name);
  const onChange = useOnChangeEvent(name, onChangeProp);
  const onBlur = useOnBlurEvent(name, onBlurProp);
  const hasError = meta.touched && meta.error;
  const isNonEditable =
    inputProps.variant === "disabled" || inputProps.variant === "readOnly";

  return (
    <InputTypeIn
      {...inputProps}
      id={name}
      name={name}
      value={field.value ?? ""}
      onChange={onChange}
      onBlur={onBlur}
      variant={
        isNonEditable
          ? inputProps.variant
          : hasError
            ? "error"
            : inputProps.variant
      }
    />
  );
}
