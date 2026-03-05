import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";

interface DisplayNameFieldProps {
  disabled?: boolean;
}

export function DisplayNameField({ disabled = false }: DisplayNameFieldProps) {
  return (
    <InputLayouts.Vertical
      name="name"
      title="Display Name"
      description="A name which you can use to identify this provider when selecting it in the UI."
    >
      <InputTypeInField
        name="name"
        placeholder="Display Name"
        variant={disabled ? "disabled" : undefined}
      />
    </InputLayouts.Vertical>
  );
}
