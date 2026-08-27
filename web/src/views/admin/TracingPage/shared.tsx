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

  return (
    <InputVertical
      title={
        field.optional
          ? t("field.optional.title", { label: field.label })
          : field.label
      }
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

interface ConfigFieldProps {
  field: TracingFieldSpec;
}

export function ConfigField({ field }: ConfigFieldProps) {
  const t = useTranslations("admin.tracing");

  return (
    <InputVertical
      title={
        field.optional
          ? t("field.optional.title", { label: field.label })
          : field.label
      }
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
