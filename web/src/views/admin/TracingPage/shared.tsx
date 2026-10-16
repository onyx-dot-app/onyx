"use client";

import { useTranslations } from "next-intl";
import { markdown } from "@opal/utils";
import { InputVertical } from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import type { TracingFieldSpec } from "@/lib/tracing/utils";

interface ConfigFieldProps {
  field: TracingFieldSpec;
  /** Formik path of the field. @default field.name */
  name?: string;
}

export function ConfigField({ field, name = field.name }: ConfigFieldProps) {
  const t = useTranslations("admin.tracing");
  const label = t(field.labelKey);

  return (
    <InputVertical
      title={field.optional ? t("field.optional.title", { label }) : label}
      withLabel={name}
      subDescription={
        field.descriptionKey ? markdown(t(field.descriptionKey)) : undefined
      }
    >
      <InputTypeInField
        name={name}
        placeholder={field.placeholderKey ? t(field.placeholderKey) : ""}
      />
    </InputVertical>
  );
}
