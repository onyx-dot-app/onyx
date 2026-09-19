import {
  useFormContext,
  type Control,
  type FieldValues,
} from "react-hook-form";

// Explicit `control` prop wins, else the nearest <FormProvider>, keeping the provider optional.
export function useFieldController<TFieldValues extends FieldValues>(
  explicit?: Control<TFieldValues>,
): Control<TFieldValues> {
  // useFormContext returns null outside a provider, so the optional chain matters.
  const context = useFormContext<TFieldValues>();
  const control = explicit ?? context?.control;
  if (!control) {
    throw new Error(
      "A form field needs a `control` prop or a <FormProvider> ancestor.",
    );
  }
  return control;
}
