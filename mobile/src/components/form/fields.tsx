// Binds via `useController`, never `register` — RN `TextInput` emits `onChangeText`, not a DOM event.
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

// RN TextInput only handles strings; binding a number/boolean field would corrupt form state.
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
  control?: Control<TFieldValues>;
  rules?: FieldRules<TFieldValues, TName>;
  title: string;
  description?: string;
  subDescription?: string;
  suffix?: "optional" | (string & {});
  /** Value still submits while disabled. */
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

// Fallback message keeps the error variant and a11y alert in lockstep when an error has no message.
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
    | "prefixText"
    | "clearButton"
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
      disabled={disabled}
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
      disabled={disabled}
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
