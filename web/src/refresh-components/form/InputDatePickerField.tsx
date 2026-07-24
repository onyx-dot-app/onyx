"use client";

import { useField } from "formik";
import { InputDatePicker, type InputDatePickerProps } from "@opal/components";
import { useOnChangeValue } from "@/hooks/formHooks";

interface InputDatePickerFieldProps extends Omit<
  InputDatePickerProps,
  "value" | "onChange" | "id"
> {
  name: string;
  setSelectedDate?: (date: Date | null) => void;
}

export default function InputDatePickerField({
  name,
  setSelectedDate,
  ...props
}: InputDatePickerFieldProps) {
  const [field] = useField<Date | null>(name);
  const onChange = useOnChangeValue(name, setSelectedDate);

  return (
    <InputDatePicker
      {...props}
      id={name}
      value={field.value}
      onChange={onChange}
    />
  );
}
