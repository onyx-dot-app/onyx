"use client";

import { useCallback } from "react";
import { useField } from "formik";

export function useOnChangeEvent<T = any>(
  name: string,
  f?: (event: T) => void
) {
  const [field] = useField<T>(name);
  return useCallback(
    (event: T) => {
      field.onChange(event);
      f?.(event);
    },
    [field, f]
  );
}

export function useOnChangeValue<T = any>(
  name: string,
  f?: (value: T) => void
) {
  const [, , helpers] = useField<T>(name);
  return useCallback(
    (value: T) => {
      helpers.setValue(value);
      helpers.setTouched(true);
      f?.(value);
    },
    [helpers, f]
  );
}

export function useOnBlurEvent<T = any>(name: string, f?: (event: T) => void) {
  const [field] = useField<T>(name);
  return useCallback(
    (event: T) => {
      f?.(event);
      field.onBlur(event);
    },
    [field, f]
  );
}
