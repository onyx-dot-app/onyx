"use client";

import { useField } from "formik";
import InputDatePicker, {
  InputDatePickerProps,
} from "@/refresh-components/inputs/InputDatePicker";

interface InputDatePickerFieldProps
  extends Omit<InputDatePickerProps, "selectedDate" | "setSelectedDate"> {
  name: string;
}

export default function InputDatePickerField({
  name,
  ...props
}: InputDatePickerFieldProps) {
  const [field, , helpers] = useField<Date | null>(name);

  return (
    <InputDatePicker
      selectedDate={field.value}
      setSelectedDate={(date) => {
        helpers.setValue(date);
        helpers.setTouched(true);
      }}
      {...props}
    />
  );
}
