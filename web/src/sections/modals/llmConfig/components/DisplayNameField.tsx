import { TextFormField } from "@/components/Field";

interface DisplayNameFieldProps {
  disabled?: boolean;
}

export function DisplayNameField({ disabled = false }: DisplayNameFieldProps) {
  return (
    <TextFormField
      name="name"
      label="Display Name"
      subtext="A name which you can use to identify this provider when selecting it in the UI."
      placeholder="Display Name"
      disabled={disabled}
    />
  );
}
