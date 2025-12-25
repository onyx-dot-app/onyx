"use client";

import { useField } from "formik";
import InputDatePicker, {
  InputDatePickerProps,
} from "@/refresh-components/inputs/InputDatePicker";
import { useOnChangeValue } from "@/hooks/formHooks";

interface InputDatePickerFieldProps
  extends Omit<InputDatePickerProps, "selectedDate" | "setSelectedDate"> {
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
      selectedDate={field.value}
      setSelectedDate={onChange}
      {...props}
    />
  );
}
