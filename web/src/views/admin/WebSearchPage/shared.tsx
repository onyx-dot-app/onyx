"use client";

import { markdown } from "@opal/utils";
import type { RichStr } from "@opal/types";
import { InputVertical } from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";

interface ApiKeyFieldProps {
  providerLabel: string;
  apiKeyUrl?: string;
}

export function ApiKeyField({ providerLabel, apiKeyUrl }: ApiKeyFieldProps) {
  return (
    <InputVertical
      title="API Key"
      withLabel="api_key"
      subDescription={markdown(
        apiKeyUrl
          ? `Paste your [API key](${apiKeyUrl}) from ${providerLabel} to connect.`
          : `Paste your API key from ${providerLabel} to connect.`
      )}
    >
      <PasswordInputTypeInField name="api_key" placeholder="API Key" />
    </InputVertical>
  );
}

interface ConfigTextFieldProps {
  title: string;
  placeholder: string;
  subDescription?: string | RichStr;
}

export function ConfigTextField({
  title,
  placeholder,
  subDescription,
}: ConfigTextFieldProps) {
  return (
    <InputVertical
      title={title}
      withLabel="config"
      subDescription={subDescription}
    >
      <InputTypeInField name="config" placeholder={placeholder} />
    </InputVertical>
  );
}
