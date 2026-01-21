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
export function useOnChangeEvent<T = any>(
  name: string,
  f?: (event: T) => void
) {
  const [field, , helpers] = useField<T>(name);
  return (event: T) => {
    helpers.setTouched(true);
    f?.(event);
    field.onChange(event);
  };
}

/**
 * Custom hook for handling form value changes in Formik forms.
 *
 * This hook automatically sets the field as "touched" when its value changes,
 * enabling immediate validation feedback after the first user interaction.
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
 *
 * @example
 * ```tsx
 * function MyDatePicker({ name }: Props) {
 *   const [field] = useField(name);
 *   const onChange = useOnChangeValue(name);
 *
 *   return (
 *     <DatePicker selectedDate={field.value} setSelectedDate={onChange} />
 *   );
 * }
 * ```
 */
export function useOnChangeValue<T = any>(
  name: string,
  f?: (value: T) => void
) {
  const [, , helpers] = useField<T>(name);
  return (value: T) => {
    helpers.setTouched(true);
    f?.(value);
    helpers.setValue(value);
  };
}

/**
 * Custom hook for handling form input blur events in Formik forms.
 *
 * This hook chains the consumer's onBlur callback with Formik's blur handler,
 * ensuring both effects run when the field loses focus.
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
  const [field] = useField<T>(name);
  return (event: T) => {
    f?.(event);
    field.onBlur(event);
  };
}
