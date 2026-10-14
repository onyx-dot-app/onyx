"use client";

import { useField } from "formik";
import {
  InputPasswordTypeIn,
  type InputPasswordTypeInProps,
} from "@opal/components";
import { useOnChangeEvent, useOnBlurEvent } from "@/hooks/formHooks";

export interface PasswordInputTypeInFieldProps extends Omit<
  InputPasswordTypeInProps,
  "value"
> {
  name: string;
}

export default function PasswordInputTypeInField({
  name,
  onChange: onChangeProp,
  onBlur: onBlurProp,
  ...inputProps
}: PasswordInputTypeInFieldProps) {
  const [field, meta] = useField(name);
  const onChange = useOnChangeEvent(name, onChangeProp);
  const onBlur = useOnBlurEvent(name, onBlurProp);
  const hasError = meta.touched && meta.error;
  const showError = hasError && !inputProps.disabled;

  return (
    <InputPasswordTypeIn
      {...inputProps}
      id={name}
      name={name}
      value={field.value ?? ""}
      onChange={onChange}
      onBlur={onBlur}
      error={showError ? true : inputProps.error}
    />
  );
}
