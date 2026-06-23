// Public surface. Layer 1 (RHF-free): `InputLayouts` primitives + `TextInput` /
// `PasswordTextInput` atoms. Layer 2 (RHF-bound): `TextInputField` / `PasswordInputField`.
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
