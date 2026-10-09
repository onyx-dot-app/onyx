"use client";

import { useCallback } from "react";
import { useField } from "formik";
import {
  InputCheckbox,
  type InputCheckboxProps,
} from "@opal/components/inputs/booleans/input-checkbox/components";

/** Every `InputCheckbox` prop except the checked state, which Formik owns. */
type InputCheckboxFieldProps = Omit<
  InputCheckboxProps,
  "checked" | "defaultChecked"
> & {
  /** The Formik field name. */
  name: string;
};

/**
 * Formik-bound `InputCheckbox` over a `boolean` field. A change writes the
 * new state and marks the field touched; `onCheckedChange` still fires after
 * the field is updated.
 */
function InputCheckboxField({
  name,
  onCheckedChange,
  ...checkboxProps
}: InputCheckboxFieldProps) {
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
    <InputCheckbox
      {...checkboxProps}
      name={name}
      checked={!!field.value}
      onCheckedChange={handleCheckedChange}
    />
  );
}

export { InputCheckboxField, type InputCheckboxFieldProps };
