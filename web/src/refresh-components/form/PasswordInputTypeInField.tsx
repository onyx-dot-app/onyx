"use client";

import { useField } from "formik";
import PasswordInputTypeIn, {
  PasswordInputTypeInProps,
} from "@/refresh-components/inputs/PasswordInputTypeIn";
import { useOnChangeEvent, useOnBlurEvent } from "@/hooks/formHooks";
import { FieldLabel } from "@/components/Field";

export interface PasswordInputTypeInFieldProps
  extends Omit<PasswordInputTypeInProps, "value"> {
  name: string;
  /** Optional label to display above the input */
  label?: string;
  /** Optional subtext to display below the label */
  subtext?: string;
}

export default function PasswordInputTypeInField({
  name,
  label,
  subtext,
  onChange: onChangeProp,
  onBlur: onBlurProp,
  placeholder,
  ...inputProps
}: PasswordInputTypeInFieldProps) {
  const [field, meta] = useField(name);
  const onChange = useOnChangeEvent(name, onChangeProp);
  const onBlur = useOnBlurEvent(name, onBlurProp);
  const hasError = meta.touched && meta.error;
  // Don't show error styling for disabled fields
  const showError = hasError && !inputProps.disabled;

  const input = (
    <PasswordInputTypeIn
      {...inputProps}
      id={name}
      name={name}
      value={field.value ?? ""}
      onChange={onChange}
      onBlur={onBlur}
      placeholder={placeholder ?? label ?? "API Key"}
      error={showError ? true : inputProps.error}
    />
  );

  if (!label) {
    return input;
  }

  return (
    <div className="w-full flex flex-col gap-1">
      <FieldLabel name={name} label={label} subtext={subtext} />
      {input}
    </div>
  );
}
