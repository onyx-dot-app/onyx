// Bound field atoms — Layer 2, the only form components that know react-hook-form.
// React Native counterpart of web's `InputTypeInField` / `PasswordInputTypeInField`
// (web/src/refresh-components/form/). Each calls `useController`, sources the scoped
// `fieldState.error`, and renders a presentational `Vertical` around the matching
// input atom, so screens write one line per field. RHF binds via `useController`,
// never `register` — RN `TextInput` emits `onChangeText` (a string), not a DOM event.
import {
  useController,
  type Control,
  type FieldPath,
  type FieldPathValue,
  type FieldValues,
  type RegisterOptions,
} from "react-hook-form";

import { Vertical } from "@/components/form/input-layouts";
import { useFieldController } from "@/components/form/use-field-controller";
import {
  PasswordTextInput,
  TextInput,
  type PasswordTextInputProps,
  type TextInputProps,
  type TextInputVariant,
} from "@/components/ui/text-input";

// Names whose value is string-typed. RN TextInput only handles strings, so binding a
// number/boolean field would coerce its value to a string and corrupt form state —
// reject those bindings at compile time.
type StringFieldPath<TFieldValues extends FieldValues> = {
  [K in FieldPath<TFieldValues>]: FieldPathValue<TFieldValues, K> extends
    | string
    | undefined
    ? K
    : never;
}[FieldPath<TFieldValues>];

type FieldRules<
  TFieldValues extends FieldValues,
  TName extends FieldPath<TFieldValues>,
> = Omit<
  RegisterOptions<TFieldValues, TName>,
  "valueAsNumber" | "valueAsDate" | "setValueAs" | "disabled"
>;

interface FieldBaseProps<
  TFieldValues extends FieldValues,
  TName extends StringFieldPath<TFieldValues>,
> {
  name: TName;
  /** Optional — falls back to the nearest <FormProvider>. */
  control?: Control<TFieldValues>;
  /** Inline RHF rules; a `zodResolver` at the form level is preferred. */
  rules?: FieldRules<TFieldValues, TName>;
  title: string;
  description?: string;
  subDescription?: string;
  suffix?: "optional" | (string & {});
  /** Visually disabled + non-editable. The value stays in form state and submits. */
  disabled?: boolean;
}

function resolveVariant(
  disabled: boolean | undefined,
  hasError: boolean,
): TextInputVariant {
  if (disabled) return "disabled";
  if (hasError) return "error";
  return "idle";
}

// An error with no message (e.g. boolean `required: true`, or a schema rule without a
// message) would otherwise flip the field red with no explanation and no a11y alert.
// Returning a fallback keeps the message row and the red variant in lockstep.
function errorMessageOf(
  message: string | undefined,
  hasError: boolean,
): string | undefined {
  if (!hasError) return undefined;
  return message || "Invalid value.";
}

export type TextInputFieldProps<
  TFieldValues extends FieldValues,
  TName extends StringFieldPath<TFieldValues>,
> = FieldBaseProps<TFieldValues, TName> &
  Pick<
    TextInputProps,
    | "placeholder"
    | "keyboardType"
    | "autoCapitalize"
    | "autoComplete"
    | "autoCorrect"
    | "spellCheck"
    | "textContentType"
    | "returnKeyType"
    | "onSubmitEditing"
    | "leftIcon"
  >;

function TextInputField<
  TFieldValues extends FieldValues,
  TName extends StringFieldPath<TFieldValues>,
>({
  name,
  control: controlProp,
  rules,
  title,
  description,
  subDescription,
  suffix,
  disabled,
  ...input
}: TextInputFieldProps<TFieldValues, TName>) {
  const control = useFieldController<TFieldValues>(controlProp);
  const { field, fieldState } = useController({ name, control, rules });
  const { ref, value, onChange, onBlur } = field;
  const error = errorMessageOf(fieldState.error?.message, !!fieldState.error);
  return (
    <Vertical
      title={title}
      description={description}
      subDescription={subDescription}
      suffix={suffix}
      error={error}
    >
      <TextInput
        {...input}
        ref={ref}
        value={value ?? ""}
        onChangeText={onChange}
        onBlur={onBlur}
        variant={resolveVariant(disabled, !!error)}
        accessibilityLabel={title}
      />
    </Vertical>
  );
}

export type PasswordInputFieldProps<
  TFieldValues extends FieldValues,
  TName extends StringFieldPath<TFieldValues>,
> = FieldBaseProps<TFieldValues, TName> &
  Pick<
    PasswordTextInputProps,
    | "placeholder"
    | "autoCapitalize"
    | "autoComplete"
    | "textContentType"
    | "returnKeyType"
    | "onSubmitEditing"
    | "revealable"
  >;

function PasswordInputField<
  TFieldValues extends FieldValues,
  TName extends StringFieldPath<TFieldValues>,
>({
  name,
  control: controlProp,
  rules,
  title,
  description,
  subDescription,
  suffix,
  disabled,
  ...input
}: PasswordInputFieldProps<TFieldValues, TName>) {
  const control = useFieldController<TFieldValues>(controlProp);
  const { field, fieldState } = useController({ name, control, rules });
  const { ref, value, onChange, onBlur } = field;
  const error = errorMessageOf(fieldState.error?.message, !!fieldState.error);
  return (
    <Vertical
      title={title}
      description={description}
      subDescription={subDescription}
      suffix={suffix}
      error={error}
    >
      <PasswordTextInput
        {...input}
        ref={ref}
        value={value ?? ""}
        onChangeText={onChange}
        onBlur={onBlur}
        variant={resolveVariant(disabled, !!error)}
        accessibilityLabel={title}
      />
    </Vertical>
  );
}

export { TextInputField, PasswordInputField };
