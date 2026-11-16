"use client";

import { useCallback } from "react";
import { useField } from "formik";
import {
  InputCurrency,
  type InputCurrencyProps,
} from "@opal/components/inputs/numbers/input-currency/components";

/** Every `InputCurrency` prop except the value, which Formik owns. */
type InputCurrencyFieldProps = Omit<
  InputCurrencyProps,
  "value" | "onChange"
> & {
  /** The Formik field name. It is also the input's default `id`, so a label
   * can point at it. */
  name: string;
  /** Called after the field is updated. */
  onChange?: (value: number | null) => void;
};

/**
 * Formik-bound `InputCurrency` over a `number | null` field; cleared, the
 * field holds `null`. An edit marks the field touched, so a touched field
 * with an error shows the error state as the amount is typed.
 */
function InputCurrencyField({
  name,
  id = name,
  error,
  onChange,
  ...inputProps
}: InputCurrencyFieldProps) {
  const [field, meta, helpers] = useField<number | null>(name);
  const handleChange = useCallback(
    (value: number | null) => {
      // setValue validates with the new value; setTouched must not validate
      // again with the pre-change values, or that later result would win.
      void helpers.setValue(value);
      void helpers.setTouched(true, false);
      onChange?.(value);
    },
    [helpers, onChange]
  );
  return (
    <InputCurrency
      {...inputProps}
      id={id}
      value={field.value ?? null}
      onChange={handleChange}
      error={error || (meta.touched && meta.error !== undefined)}
    />
  );
}

export { InputCurrencyField, type InputCurrencyFieldProps };
