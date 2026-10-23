"use client";

import { useCallback } from "react";
import { useField } from "formik";
import InputNumber, {
  type InputNumberProps,
} from "@opal/components/inputs/numbers/input-number/components";
import { useOpalStrings } from "@opal/strings";

/** Every `InputNumber` prop except the value, which Formik owns. */
type InputNumberFieldProps = Omit<InputNumberProps, "value" | "onChange"> & {
  /** The Formik field name. It is also the input's default `id`, so a label
   * can point at it. */
  name: string;
  /** Called after the field is updated. */
  onChange?: (value: number | null) => void;
};

/**
 * Formik-bound `InputNumber` over a `number | undefined` field; cleared, the
 * field holds `undefined`. A typed value outside `min`..`max` is kept as
 * typed and fails the field's validation, so the form shows the error
 * instead of the input clamping it. A touched field with an error shows the
 * error state.
 */
function InputNumberField({
  name,
  id = name,
  min,
  max,
  variant,
  onChange,
  ...inputProps
}: InputNumberFieldProps) {
  const strings = useOpalStrings();
  const validate = useCallback(
    (value: number | undefined): string | undefined =>
      value !== undefined &&
      ((min !== undefined && value < min) || (max !== undefined && value > max))
        ? strings.inputNumberOutOfRange(min, max)
        : undefined,
    [min, max, strings]
  );
  const [field, meta, helpers] = useField<number | undefined>({
    name,
    validate,
  });
  const handleChange = useCallback(
    (value: number | null) => {
      // setValue validates with the new value; setTouched must not validate
      // again with the pre-change values, or that later result would win.
      void helpers.setValue(value ?? undefined);
      void helpers.setTouched(true, false);
      onChange?.(value);
    },
    [helpers, onChange]
  );
  const showError: boolean = meta.touched && meta.error !== undefined;
  return (
    <InputNumber
      {...inputProps}
      id={id}
      min={min}
      max={max}
      value={field.value ?? null}
      onChange={handleChange}
      variant={
        variant === "disabled" || variant === "readOnly"
          ? variant
          : showError
            ? "error"
            : variant
      }
    />
  );
}

export { InputNumberField, type InputNumberFieldProps };
