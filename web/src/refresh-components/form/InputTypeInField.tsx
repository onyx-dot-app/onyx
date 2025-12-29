"use client";

import { useField } from "formik";
import InputTypeIn, {
  InputTypeInProps,
} from "@/refresh-components/inputs/InputTypeIn";
import { useOnChangeEvent } from "@/hooks/formHooks";

export interface InputTypeInFieldProps
  extends Omit<InputTypeInProps, "value" | "onClear"> {
  name: string;
}

export default function InputTypeInField({
  name,
  onChange: onChangeProp,
  ...inputProps
}: InputTypeInFieldProps) {
  const [field, meta, helpers] = useField(name);
  const onChange = useOnChangeEvent(name, onChangeProp);
  const hasError = meta.touched && meta.error;

  return (
    <InputTypeIn
      {...inputProps}
      id={name}
      name={name}
      value={field.value || ""}
      onChange={onChange}
      onBlur={field.onBlur}
      onClear={() => {
        helpers.setValue("");
      }}
      error={!!hasError}
    />
  );
}
