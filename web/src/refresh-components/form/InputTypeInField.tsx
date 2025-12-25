"use client";

import { useField } from "formik";
import InputTypeIn, {
  InputTypeInProps,
} from "@/refresh-components/inputs/InputTypeIn";
import { useFormInputCallback } from "@/hooks/form-hooks";

export interface InputTypeInFieldProps
  extends Omit<InputTypeInProps, "value" | "onChange" | "onClear"> {
  name: string;
}

export default function InputTypeInField({
  name,
  ...inputProps
}: InputTypeInFieldProps) {
  const [field, meta, helpers] = useField(name);
  const onChange = useFormInputCallback(name);
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
