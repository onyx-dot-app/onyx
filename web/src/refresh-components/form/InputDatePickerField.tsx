"use client";

import { useField } from "formik";
import InputDatePicker, {
  InputDatePickerProps,
} from "@/refresh-components/inputs/InputDatePicker";
import { useFormInputCallback } from "@/hooks/form-hooks";

interface InputDatePickerFieldProps
  extends Omit<InputDatePickerProps, "selectedDate"> {
  name: string;
}

export default function InputDatePickerField({
  name,
  setSelectedDate,
  ...props
}: InputDatePickerFieldProps) {
  const [field] = useField<Date | null>(name);
  const onChange = useFormInputCallback(name, setSelectedDate);

  return (
    <InputDatePicker
      selectedDate={field.value}
      setSelectedDate={onChange}
      {...props}
    />
  );
}
