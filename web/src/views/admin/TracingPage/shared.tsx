"use client";

import { markdown } from "@opal/utils";
import { InputVertical } from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import type { TracingFieldSpec } from "@/lib/tracing/constants";

function fieldTitle(field: TracingFieldSpec): string {
  return field.optional ? `${field.label} (Optional)` : field.label;
}

export function SecretField({ field }: { field: TracingFieldSpec }) {
  return (
    <InputVertical
      title={fieldTitle(field)}
      withLabel={field.name}
      subDescription={field.help ? markdown(field.help) : undefined}
    >
      <PasswordInputTypeInField
        name={field.name}
        placeholder={field.placeholder ?? field.label}
      />
    </InputVertical>
  );
}

export function ConfigField({ field }: { field: TracingFieldSpec }) {
  return (
    <InputVertical
      title={fieldTitle(field)}
      withLabel={field.name}
      subDescription={field.help ? markdown(field.help) : undefined}
    >
      <InputTypeInField
        name={field.name}
        placeholder={field.placeholder ?? ""}
      />
    </InputVertical>
  );
}
