"use client";

import { useTranslations } from "next-intl";
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

  return (
    <InputVertical
      title={field.optional ? t("field.optional.title", { label }) : label}
      withLabel={field.name}
      subDescription={
        field.descriptionKey ? markdown(t(field.descriptionKey)) : undefined
      }
    >
      <PasswordInputTypeInField
        name={field.name}
        placeholder={
          field.placeholderKey
            ? t(field.placeholderKey)
            : (field.placeholder ?? label)
        }
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
      title={field.optional ? t("field.optional.title", { label }) : label}
      withLabel={field.name}
      subDescription={
        field.descriptionKey ? markdown(t(field.descriptionKey)) : undefined
      }
    >
      <InputTypeInField
        name={field.name}
        placeholder={
          field.placeholderKey
            ? t(field.placeholderKey)
            : (field.placeholder ?? "")
        }
      />
    </InputVertical>
  );
}
