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
 *   const [field] = useField(name);
 *   const onChange = useFormInputCallback(name);
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
  f?: (event: T) => void
) {
  const [field, , helpers] = useField<T>(name);
  return (event: T) => {
    f?.(event);
    helpers.setTouched(true);
    field.onChange(event);
  };
}
