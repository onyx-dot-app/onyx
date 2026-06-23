import {
  useFormContext,
  type Control,
  type FieldValues,
} from "react-hook-form";

// Resolves the react-hook-form `control` a bound field should bind to: an explicit
// `control` prop wins, otherwise it falls back to the nearest <FormProvider>. This
// keeps `FormProvider` optional — small forms can pass `control` directly — while
// larger forms avoid prop-drilling. Throws a clear error when neither is present.
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
