"use client";

import { useField } from "formik";

/**
 * Custom hook for handling form input changes in Formik forms.
 *
 * This hook automatically sets the field as "touched" when its value changes,
 * enabling immediate validation feedback after the first user interaction.
 *
 * @example
 * ```tsx
 * function MyField({ name }: { name: string }) {
 *   const [field, meta] = useField(name);
 *   const onChange = useFormInputCallback(name);
 *
 *   return (
 *     <input
 *       name={name}
 *       value={field.value}
 *       onChange={(e) => onChange(e.target.value)}
 *     />
 *   );
 * }
 * ```
 *
 * @example
 * ```tsx
 * // With callback
 * function MySelect({ name, onValueChange }: Props) {
 *   const [field] = useField(name);
 *   const onChange = useFormInputCallback(name, onValueChange);
 *
 *   return (
 *     <Select value={field.value} onValueChange={onChange} />
 *   );
 * }
 * ```
 */
export function useFormInputCallback<T = any>(
  name: string,
  f?: (value: T) => void
) {
  const [, , helpers] = useField<T>(name);
  return (value: T) => {
    f?.(value);
    helpers.setTouched(true);
    helpers.setValue(value);
  };
}
