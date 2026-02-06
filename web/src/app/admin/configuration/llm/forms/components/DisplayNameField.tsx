import { TextFormField } from "@/components/Field";
import Text from "@/refresh-components/texts/Text";
import * as GeneralLayouts from "@/layouts/general-layouts";

interface DisplayNameFieldProps {
  disabled?: boolean;
}

export function DisplayNameField({ disabled = false }: DisplayNameFieldProps) {
  return (
    <GeneralLayouts.Section gap={0.25} alignItems="stretch">
      <TextFormField
        name="name"
        label="Display Name (Optional)"
        placeholder="Display Name"
        disabled={disabled}
      />
      <Text as="p" secondaryBody text03>
        Use to identify this provider in the app
      </Text>
    </GeneralLayouts.Section>
  );
}
