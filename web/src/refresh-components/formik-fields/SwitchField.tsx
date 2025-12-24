"use client";

import { useField } from "formik";
import Switch, { SwitchProps } from "@/refresh-components/inputs/Switch";

interface SwitchFieldProps extends Omit<SwitchProps, "checked"> {
  name: string;
}

export default function SwitchField({
  name,
  onCheckedChange,
  ...props
}: SwitchFieldProps) {
  const [field, , helpers] = useField<boolean>({ name, type: "checkbox" });

  return (
    <Switch
      id={name}
      checked={field.value}
      onCheckedChange={(checked) => {
        helpers.setValue(Boolean(checked));
        helpers.setTouched(true);
        onCheckedChange?.(checked);
      }}
      }}
      {...props}
    />
  );
}
