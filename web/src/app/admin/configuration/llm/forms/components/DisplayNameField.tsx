import { TextFormField } from "@/components/Field";

interface DisplayNameFieldProps {
  disabled?: boolean;
}

export function DisplayNameField({ disabled = false }: DisplayNameFieldProps) {
  return (
    <TextFormField
      name="name"
      subtext={"Use to identify this provider in the app"}
      label="Display Name (Optional)"
      placeholder="Display Name"
      disabled={disabled}
    />
  );
}
