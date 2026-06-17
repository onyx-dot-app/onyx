"use client";

import { useField } from "formik";
import { Switch, type SwitchProps } from "@opal/components";
import { useOnChangeValue } from "@/hooks/formHooks";

interface SwitchFieldProps extends Omit<SwitchProps, "checked"> {
  name: string;
}

export default function SwitchField({
  name,
  onCheckedChange,
  ...props
}: SwitchFieldProps) {
  const [field] = useField<boolean>({ name, type: "checkbox" });
  const onChange = useOnChangeValue(name, onCheckedChange);

  return (
    <Switch
      id={name}
      name={name}
      checked={field.value}
      onCheckedChange={onChange}
      {...props}
    />
  );
}
