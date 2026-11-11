"use client";

import { useTranslations } from "next-intl";
import { useField } from "formik";
import { markdown } from "@opal/utils";
import { InputVertical } from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import type { TracingFieldSpec } from "@/lib/tracing/utils";

interface SecretFieldProps {
  field: TracingFieldSpec;
}

export function SecretField({ field }: SecretFieldProps) {
  const t = useTranslations("admin.tracing");
  const label = t(field.labelKey);
  // On edit, the initial value is the stored masked key.
  const [, meta] = useField<string>(field.name);

  return (
    <InputVertical
      title={label}
      suffix={field.optional ? "optional" : undefined}
      withLabel={field.name}
      subDescription={
        field.descriptionKey ? markdown(t(field.descriptionKey)) : undefined
      }
    >
      <PasswordInputTypeInField
        name={field.name}
        placeholder={field.placeholderKey ? t(field.placeholderKey) : label}
        existingValue={meta.initialValue}
      />
    </InputVertical>
  );
}

interface ConfigFieldProps {
  field: TracingFieldSpec;
}

export function ConfigField({ field }: ConfigFieldProps) {
  const t = useTranslations("admin.tracing");
  const label = t(field.labelKey);

  return (
    <InputVertical
      title={label}
      suffix={field.optional ? "optional" : undefined}
      withLabel={field.name}
      subDescription={
        field.descriptionKey ? markdown(t(field.descriptionKey)) : undefined
      }
    >
      <InputTypeInField
        name={field.name}
        placeholder={field.placeholderKey ? t(field.placeholderKey) : ""}
      />
    </InputVertical>
  );
}
