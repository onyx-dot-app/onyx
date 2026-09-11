"use client";

import { useField } from "formik";
import { InputCheckbox, type InputCheckboxProps } from "@opal/components";
import { useOnChangeValue } from "@/hooks/formHooks";

interface CheckboxFieldProps extends Omit<InputCheckboxProps, "checked"> {
  name: string;
}

export default function UnlabeledCheckboxField({
  name,
  onCheckedChange,
  ...props
}: CheckboxFieldProps) {
  const [field] = useField<boolean>({ name, type: "checkbox" });
  const onChange = useOnChangeValue(name, onCheckedChange);

  return (
    <InputCheckbox checked={field.value} onCheckedChange={onChange} {...props} />
  );
}
