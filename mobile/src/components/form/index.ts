// Public surface of the form library.
//
// Layer 1 (presentational, RHF-free): the `InputLayouts` primitives + the
// `TextInput` / `PasswordTextInput` atoms — usable on their own with a plain
// `error` string, or via react-hook-form's `<Controller>` for custom inputs.
// Layer 2 (RHF-bound): `TextInputField` / `PasswordInputField` — one line per field.
import {
  InputDivider,
  InputErrorText,
  InputPadder,
  Horizontal,
  Label,
  Vertical,
} from "@/components/form/input-layouts";

export {
  Vertical,
  Horizontal,
  Label,
  InputErrorText,
  InputDivider,
  InputPadder,
};
export type {
  VerticalProps,
  HorizontalProps,
  LabelProps,
  InputErrorTextProps,
  InputPadderProps,
  InputErrorType,
} from "@/components/form/input-layouts";

/** Namespace for web-parity ergonomics: `<InputLayouts.Vertical .../>`. */
export const InputLayouts = {
  Vertical,
  Horizontal,
  Label,
  InputErrorText,
  InputDivider,
  InputPadder,
};

export { TextInputField, PasswordInputField } from "@/components/form/fields";
export type {
  TextInputFieldProps,
  PasswordInputFieldProps,
} from "@/components/form/fields";

export { TextInput, PasswordTextInput } from "@/components/ui/text-input";
export type {
  TextInputProps,
  PasswordTextInputProps,
  TextInputVariant,
} from "@/components/ui/text-input";
