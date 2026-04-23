"use client";

import { useField } from "formik";
import InputComboBox, {
  InputComboBoxProps,
} from "@/refresh-components/inputs/InputComboBox";
import { useOnChangeEvent, useOnChangeValue } from "@/hooks/formHooks";

export interface InputComboBoxFieldProps
  extends Omit<InputComboBoxProps, "value"> {
  name: string;
}

export default function InputComboBoxField({
  name,
  onChange: onChangeProp,
  onValueChange: onValueChangeProp,
  ...inputProps
}: InputComboBoxFieldProps) {
  const [field, meta] = useField<string>(name);
  const onChange = useOnChangeEvent(name, onChangeProp);
  const onValueChange = useOnChangeValue(name, onValueChangeProp);
  const hasError = meta.touched && meta.error;

  return (
    <InputComboBox
      {...inputProps}
      name={name}
      value={field.value ?? ""}
      onChange={onChange}
      onValueChange={onValueChange}
      isError={hasError ? true : inputProps.isError}
    />
  );
}
