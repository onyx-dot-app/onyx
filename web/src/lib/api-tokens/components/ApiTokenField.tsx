"use client";

import { useField } from "formik";
import { useTranslations } from "next-intl";
import { InputVertical } from "@opal/layouts";
import type { RichStr } from "@opal/types";
import { ApiTokenInput } from "@/lib/api-tokens/components/ApiTokenInput";
import { useApiTokens } from "@/lib/api-tokens/hooks";
import { EMPTY_API_TOKEN_VALUE } from "@/lib/api-tokens/constants";
import { getApiTokenPlatformLabel } from "@/lib/api-tokens/utils";
import type { ApiTokenPlatform, ApiTokenValue } from "@/lib/api-tokens/types";

export interface ApiTokenFieldProps {
  /** Formik field name. Its value is an `ApiTokenValue`. @default "api_key" */
  name?: string;
  platform: ApiTokenPlatform;
  optional?: boolean;
  /** Replaces the shared sub-description, for a field that needs more. */
  subDescription?: string | RichStr;
  /** See `ApiTokenInput`. */
  savedMaskedValue?: string;
  disabled?: boolean;
}

/** The API key field every form uses: one title, description and input. */
export function ApiTokenField({
  name = "api_key",
  platform,
  optional = false,
  subDescription,
  savedMaskedValue,
  disabled = false,
}: ApiTokenFieldProps) {
  const t = useTranslations("common.apiTokens");
  const [field, meta, helpers] = useField<ApiTokenValue | undefined>(name);
  const { tokens } = useApiTokens(platform);
  const platformLabel = getApiTokenPlatformLabel(platform);

  return (
    <InputVertical
      withLabel={name}
      title={t("field.title")}
      suffix={optional ? "optional" : undefined}
      subDescription={
        subDescription ??
        t(tokens.length > 0 ? "field.reuseDescription" : "field.description", {
          platform: platformLabel,
        })
      }
    >
      <ApiTokenInput
        id={name}
        name={name}
        platform={platform}
        value={field.value ?? EMPTY_API_TOKEN_VALUE}
        onChange={(value) => void helpers.setValue(value)}
        onBlur={() => void helpers.setTouched(true)}
        savedMaskedValue={savedMaskedValue}
        disabled={disabled}
        error={Boolean(meta.touched && meta.error)}
      />
    </InputVertical>
  );
}
