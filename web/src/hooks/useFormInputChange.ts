"use client";

import { useField } from "formik";

/**
 * Custom hook for handling form input changes in Formik forms.
 *
 * This hook automatically sets the field as "touched" when its value changes,
 * enabling immediate validation feedback after the first user interaction.
 *
 * @template T - The type of the field value
 * @param {string} name - The name of the Formik field
 * @param {(value: T) => void} [f] - Optional callback function to execute when the value changes
 * @returns {(value: T) => void} A function that updates the field value and marks it as touched
 *
 * @example
 * ```tsx
 * function MyField({ name }: { name: string }) {
 *   const [field, meta] = useField(name);
 *   const onChange = useOnChange(name);
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
 *   const onChange = useOnChange(name, onValueChange);
 *
 *   return (
 *     <Select value={field.value} onValueChange={onChange} />
 *   );
 * }
 * ```
 */
export function useOnChange<T = any>(name: string, f?: (value: T) => void) {
  const [field, , helpers] = useField<T>(name);
  return (value: T) => {
    f?.(value);
    helpers.setTouched(true);
    field.onChange(value);
  };
}
