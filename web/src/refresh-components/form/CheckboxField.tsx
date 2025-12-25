"use client";

import { useField } from "formik";
import Checkbox, { CheckboxProps } from "@/refresh-components/inputs/Checkbox";
import { useOnChange } from "@/hooks/useFormInputChange";

interface CheckboxFieldProps extends Omit<CheckboxProps, "checked"> {
  name: string;
}

export default function UnlabeledCheckboxField({
  name,
  onCheckedChange,
  ...props
}: CheckboxFieldProps) {
  const [field] = useField<boolean>({ name, type: "checkbox" });
  const onChange = useOnChange<boolean>(name, onCheckedChange);

  return (
    <Checkbox
      checked={field.value}
      onCheckedChange={(checked) => onChange(Boolean(checked))}
      {...props}
    />
  );
}
