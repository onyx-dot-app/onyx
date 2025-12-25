"use client";

import { useField } from "formik";
import Switch, { SwitchProps } from "@/refresh-components/inputs/Switch";
import { useFormInputCallback } from "@/hooks/form-hooks";

interface SwitchFieldProps extends Omit<SwitchProps, "checked"> {
  name: string;
}

export default function SwitchField({
  name,
  onCheckedChange,
  ...props
}: SwitchFieldProps) {
  const [field] = useField<boolean>({ name, type: "checkbox" });
  const onChange = useFormInputCallback<boolean>(name, onCheckedChange);

  return (
    <Switch
      id={name}
      checked={field.value}
      onCheckedChange={(checked) => onChange(Boolean(checked))}
      {...props}
    />
  );
}
