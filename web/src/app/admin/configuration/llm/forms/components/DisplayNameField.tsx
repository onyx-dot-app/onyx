import { TextFormField } from "@/components/Field";
import Text from "@/refresh-components/texts/Text";
import * as GeneralLayouts from "@/layouts/general-layouts";
import InputWrapper from "./InputWrapper";

interface DisplayNameFieldProps {
  disabled?: boolean;
}

export function DisplayNameField({ disabled = false }: DisplayNameFieldProps) {
  return (
    <InputWrapper
      label="Display Name"
      optional
      description="Use to identify this provider in the app"
    >
      <TextFormField
        name="name"
        label=""
        placeholder="Display Name"
        disabled={disabled}
      />
    </InputWrapper>
  );
}
