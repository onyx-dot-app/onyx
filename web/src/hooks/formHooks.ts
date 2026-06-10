"use client";

import { useCallback } from "react";
import { useField } from "formik";

/**
 * Custom hook for handling form input changes in Formik forms.
 *
 * @example
 * ```tsx
 * function MyField({ name }: { name: string }) {
 *   const [field] = useField(name);
 *   const onChange = useOnChangeEvent(name);
 *
 *   return (
 *     <input
 *       name={name}
 *       value={field.value}
 *       onChange={onChange}
 *     />
 *   );
 * }
 * ```
 */
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

/**
 * Custom hook for handling form value changes in Formik forms.
 * Use this for components that pass values directly (not events).
 *
 * @example
 * ```tsx
 * function MySelect({ name, onValueChange }: Props) {
 *   const [field] = useField(name);
 *   const onChange = useOnChangeValue(name, onValueChange);
 *
 *   return (
 *     <Select value={field.value} onValueChange={onChange} />
 *   );
 * }
 * ```
 */
export function useOnChangeValue<T = any>(
  name: string,
  f?: (value: T) => void
) {
  const [, , helpers] = useField<T>(name);
  return useCallback(
    (value: T) => {
      helpers.setTouched(true);
      helpers.setValue(value);
      f?.(value);
    },
    [helpers, f]
  );
}

/**
 * Custom hook for handling form input blur events in Formik forms.
 *
 * @example
 * ```tsx
 * function MyField({ name, onBlur }: Props) {
 *   const [field] = useField(name);
 *   const handleBlur = useOnBlurEvent(name, onBlur);
 *
 *   return (
 *     <input
 *       name={name}
 *       value={field.value}
 *       onBlur={handleBlur}
 *     />
 *   );
 * }
 * ```
 */
export function useOnBlurEvent<T = any>(name: string, f?: (event: T) => void) {
  const [field, , helpers] = useField<T>(name);
  return useCallback(
    (event: T) => {
      f?.(event);
      field.onBlur(event);
      helpers.setTouched(true);
    },
    [field, helpers, f]
  );
}
