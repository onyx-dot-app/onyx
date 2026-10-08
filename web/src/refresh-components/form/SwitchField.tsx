"use client";

import { useField } from "formik";
import { InputSwitch, type InputSwitchProps } from "@opal/components";
import { useOnChangeValue } from "@/hooks/formHooks";

interface SwitchFieldProps extends Omit<InputSwitchProps, "checked"> {
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
    <InputSwitch
      id={name}
      name={name}
      checked={field.value}
      onCheckedChange={onChange}
      {...props}
    />
  );
}
