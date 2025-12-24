"use client";

import { useField } from "formik";
import Switch, { SwitchProps } from "@/refresh-components/inputs/Switch";

interface SwitchFieldProps extends Omit<SwitchProps, "checked"> {
  name: string;
}

export default function UnlabeledSwitchField({
  name,
  onCheckedChange,
  ...props
}: SwitchFieldProps) {
  const [field, , helpers] = useField<boolean>({ name, type: "checkbox" });

  return (
    <Switch
      checked={field.value}
      onCheckedChange={(checked) => {
        helpers.setValue(Boolean(checked));
        onCheckedChange?.(checked);
      }}
      {...props}
    />
  );
}
