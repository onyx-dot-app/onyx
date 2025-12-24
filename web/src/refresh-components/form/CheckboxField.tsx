"use client";

import { useField } from "formik";
import Checkbox, { CheckboxProps } from "@/refresh-components/inputs/Checkbox";

interface CheckboxFieldProps extends Omit<CheckboxProps, "checked"> {
  name: string;
}

export default function UnlabeledCheckboxField({
  name,
  onCheckedChange,
  ...props
}: CheckboxFieldProps) {
  const [field, , helpers] = useField<boolean>({ name, type: "checkbox" });

  return (
    <Checkbox
      checked={field.value}
      onCheckedChange={(checked) => {
        helpers.setValue(Boolean(checked));
        helpers.setTouched(true);
        onCheckedChange?.(checked);
      }}
      {...props}
    />
  );
}
