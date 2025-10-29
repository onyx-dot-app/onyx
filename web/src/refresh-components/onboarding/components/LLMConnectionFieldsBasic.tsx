import React from "react";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { Separator } from "@/components/ui/separator";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import InputFile from "@/refresh-components/inputs/InputFile";

type Props = {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  modalContent?: any;
  modelOptions: Array<{ label: string; value: string }>;
  showApiMessage: boolean;
  apiStatus: "idle" | "loading" | "success" | "error";
  errorMessage: string;
  isFetchingModels: boolean;
  onApiKeyBlur: (apiKey: string) => void;
  formikValues: any;
  setDefaultModelName: (value: string) => void;
};

export const LLMConnectionFieldsBasic: React.FC<Props> = ({
  llmDescriptor,
  modalContent,
  modelOptions,
  showApiMessage,
  apiStatus,
  errorMessage,
  isFetchingModels,
  onApiKeyBlur,
  formikValues,
  setDefaultModelName,
}) => {
  return (
    <>
      {llmDescriptor?.name === "azure" ? (
        <FormikField<string>
          name="target_uri"
          render={(field, helper, meta, state) => (
            <FormField name="target_uri" state={state} className="w-full">
              <FormField.Label>Target URI</FormField.Label>
              <FormField.Control>
                <InputTypeIn
                  {...field}
                  placeholder="https://your-resource.cognitiveservices.azure.com/openai/deployments/deployment-name/chat/completions?api-version=2025-01-01-preview"
                  showClearButton={false}
                />
              </FormField.Control>
              <FormField.Description>
                Paste your endpoint target URI from
                <a
                  href="https://oai.azure.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline"
                >
                  Azure OpenAI
                </a>{" "}
                (including API endpoint base, deployment name, and API version).
              </FormField.Description>
            </FormField>
          )}
        />
      ) : (
        <>
          {llmDescriptor?.api_base_required && (
            <FormikField<string>
              name="api_base"
              render={(field, helper, meta, state) => (
                <FormField name="api_base" state={state} className="w-full">
                  <FormField.Label>API Base</FormField.Label>
                  <FormField.Control>
                    <InputTypeIn
                      {...field}
                      placeholder="API Base"
                      showClearButton={false}
                    />
                  </FormField.Control>
                </FormField>
              )}
            />
          )}
          {llmDescriptor?.api_version_required && (
            <FormikField<string>
              name="api_version"
              render={(field, helper, meta, state) => (
                <FormField name="api_version" state={state} className="w-full">
                  <FormField.Label>API Version</FormField.Label>
                  <FormField.Control>
                    <InputTypeIn
                      {...field}
                      placeholder="API Version"
                      showClearButton={false}
                    />
                  </FormField.Control>
                </FormField>
              )}
            />
          )}
        </>
      )}

      {llmDescriptor?.api_key_required && (
        <FormikField<string>
          name="api_key"
          render={(field, helper, meta, state) => (
            <FormField name="api_key" state={state} className="w-full">
              <FormField.Label>API Key</FormField.Label>
              <FormField.Control>
                <PasswordInputTypeIn
                  {...field}
                  placeholder=""
                  onBlur={(e) => {
                    field.onBlur(e);
                    if (field.value) {
                      onApiKeyBlur(field.value);
                    }
                  }}
                  showClearButton={false}
                  disabled={
                    llmDescriptor?.name === "azure" &&
                    !formikValues.target_uri?.trim()
                  }
                />
              </FormField.Control>
              {!showApiMessage && (
                <FormField.Description>
                  {"Paste your "}
                  {modalContent?.field_metadata?.api_key ? (
                    <a
                      href={modalContent.field_metadata.api_key}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline"
                    >
                      API key
                    </a>
                  ) : (
                    "API key"
                  )}
                  {` from ${modalContent?.display_name} to access your models.`}
                </FormField.Description>
              )}
              {showApiMessage && (
                <FormField.APIMessage
                  state={apiStatus}
                  messages={{
                    loading: `Checking API key with ${modalContent?.display_name}...`,
                    success: "API key valid. Your available models updated.",
                    error: errorMessage || "Invalid API key",
                  }}
                />
              )}
            </FormField>
          )}
        />
      )}

      {llmDescriptor?.custom_config_keys?.map((customConfigKey) => (
        <FormikField<string>
          key={customConfigKey.name}
          name={`custom_config.${customConfigKey.name}`}
          render={(field, helper, meta, state) => (
            <FormField
              name={`custom_config.${customConfigKey.name}`}
              state={state}
              className="w-full"
            >
              <FormField.Label>
                {customConfigKey.display_name || customConfigKey.name}
              </FormField.Label>
              <FormField.Control>
                {customConfigKey.key_type === "select" ? (
                  <InputSelect
                    value={field.value}
                    onValueChange={(value) => helper.setValue(value)}
                    options={
                      customConfigKey.options?.map((opt) => ({
                        label: opt.label,
                        value: opt.value,
                      })) ?? []
                    }
                  />
                ) : customConfigKey.key_type === "file_input" ? (
                  <InputFile
                    placeholder={customConfigKey.default_value || ""}
                    setValue={(value) => helper.setValue(value)}
                    onBlur={(e) => {
                      field.onBlur(e);
                      if (field.value) {
                        onApiKeyBlur(field.value);
                      }
                    }}
                    showClearButton={true}
                  />
                ) : customConfigKey.is_secret ? (
                  <PasswordInputTypeIn
                    {...field}
                    placeholder={customConfigKey.default_value || ""}
                    showClearButton={false}
                  />
                ) : (
                  <InputTypeIn
                    {...field}
                    placeholder={customConfigKey.default_value || ""}
                    showClearButton={false}
                  />
                )}
              </FormField.Control>
              {customConfigKey.description && (
                <FormField.Description>
                  {customConfigKey.description}
                </FormField.Description>
              )}
            </FormField>
          )}
        />
      ))}

      <Separator className="my-0" />

      <FormikField<string>
        name="default_model_name"
        render={(field, helper, meta, state) => (
          <FormField name="default_model_name" state={state} className="w-full">
            <FormField.Label>Default Model</FormField.Label>
            <FormField.Control>
              {modelOptions.length > 0 && (
                <InputSelect
                  value={field.value}
                  onValueChange={(value) => {
                    helper.setValue(value);
                    setDefaultModelName(value);
                  }}
                  options={modelOptions}
                  disabled={modelOptions.length === 0 || isFetchingModels}
                />
              )}
              {modelOptions.length === 0 && (
                <InputTypeIn
                  value={field.value}
                  onChange={(e) => {
                    helper.setValue(e.target.value);
                    setDefaultModelName(e.target.value);
                  }}
                  placeholder="E.g. gpt-4"
                  showClearButton={false}
                />
              )}
            </FormField.Control>
            <FormField.Description>
              {modalContent?.field_metadata?.default_model_name}
            </FormField.Description>
          </FormField>
        )}
      />
    </>
  );
};
