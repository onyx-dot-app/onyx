"use client";

import { useCallback } from "react";
import { useField } from "formik";
import {
  InputSwitch,
  type InputSwitchProps,
} from "@opal/components/inputs/booleans/input-switch/components";

/** Every `InputSwitch` prop except the checked state, which Formik owns. */
type InputSwitchFieldProps = Omit<
  InputSwitchProps,
  "checked" | "defaultChecked"
> & {
  /** The Formik field name. It is also the switch's default `id`, so a label
   * can point at it. */
  name: string;
};

/**
 * Formik-bound `InputSwitch` over a `boolean` field. A change writes the new
 * state and marks the field touched; `onCheckedChange` still fires after the
 * field is updated.
 */
function InputSwitchField({
  name,
  id = name,
  onCheckedChange,
  ...switchProps
}: InputSwitchFieldProps) {
  const [field, , helpers] = useField<boolean>(name);
  const handleCheckedChange = useCallback(
    (checked: boolean) => {
      // setValue validates with the new value; setTouched must not validate
      // again with the pre-change values, or that later result would win.
      void helpers.setValue(checked);
      void helpers.setTouched(true, false);
      onCheckedChange?.(checked);
    },
    [helpers, onCheckedChange]
  );
  return (
    <InputSwitch
      {...switchProps}
      id={id}
      name={name}
      checked={!!field.value}
      onCheckedChange={handleCheckedChange}
    />
  );
}

export { InputSwitchField, type InputSwitchFieldProps };
