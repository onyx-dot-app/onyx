"use client";

import { InputPasswordTypeIn, InputTypeIn } from "@opal/components";
import { InputVertical } from "@opal/layouts";
import type { CredentialField } from "@/lib/integrations/types";

interface CredentialFieldInputsProps {
  fields: CredentialField[];
  values: Record<string, string>;
  onChange: (values: Record<string, string>) => void;
  disabled: boolean;
  error?: (field: CredentialField) => string | undefined;
}

export default function CredentialFieldInputs({
  fields,
  values,
  onChange,
  disabled,
  error,
}: CredentialFieldInputsProps) {
  return fields.map((field) => {
    const value = values[field.key] ?? "";
    const change = (next: string) => onChange({ ...values, [field.key]: next });
    return (
      <InputVertical key={field.key} title={field.label} error={error?.(field)}>
        {field.secret ? (
          <InputPasswordTypeIn
            aria-label={field.label}
            value={value}
            disabled={disabled}
            onChange={(event) => change(event.target.value)}
          />
        ) : (
          <InputTypeIn
            aria-label={field.label}
            value={value}
            variant={disabled ? "disabled" : "primary"}
            onChange={(event) => change(event.target.value)}
          />
        )}
      </InputVertical>
    );
  });
}
